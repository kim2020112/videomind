"""目录同步执行器：按页限额读取投稿，状态与断点写 blogger_syncs。

不进 background_jobs 重任务队列，避免被长批次饿死。同 creator 同时只跑一个同步。
风控、请求预算或保护拦截后暂停，只有尚未取得页面的网络错误可延迟重试。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from core.blogger import store
from core.blogger.catalog import (
    BilibiliCatalogClient,
    CatalogError,
    is_lesson_entry,
    parse_length,
)
from core.logging_config import get_logger

logger = get_logger("blogger.sync")

PAGE_SIZE = 30
MAX_PAGES_PER_SYNC = 20

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="blogger-sync")
_creator_locks: dict[int, threading.Lock] = {}
_creator_locks_guard = threading.Lock()

# 错误分类 → (最大自动重试次数, 退避秒数序列)
_RETRY_POLICY = {
    "network": (2, [30, 120]),
}
_PAUSE_CODES = frozenset({"login", "rate_limit", "budget", "protection"})


def _creator_lock(creator_id: int) -> threading.Lock:
    with _creator_locks_guard:
        lock = _creator_locks.get(creator_id)
        if lock is None:
            lock = threading.Lock()
            _creator_locks[creator_id] = lock
        return lock


def start_sync(creator_id: int, *, refresh_profile: bool = True, mode: str = "incremental") -> int:
    """创建 sync 行并提交后台执行，立即返回 sync_id。"""
    previous = store.latest_sync(creator_id)
    if mode == "incremental" and not store.has_full_catalog_sync(creator_id):
        mode = "deep"
    if previous and previous["status"] == "paused" and previous["page"]:
        # 增量扫描也可能中途暂停；保留断点，避免下一次把已插入的首页误判为追平。
        mode = "deep"
    checkpoint = previous if mode == "deep" else None
    if checkpoint and (checkpoint["status"] not in ("paused", "failed", "interrupted") or not checkpoint["page"] or checkpoint["error_code"] == "api"):
        checkpoint = None
    sync_id = store.create_sync(creator_id, status="queued")
    store.update_sync(sync_id, mode=mode if mode in ("incremental", "deep") else "incremental")
    if checkpoint:
        store.update_sync(sync_id, **{key: checkpoint[key] for key in ("page", "found", "added", "expected")})
    _executor.submit(_run_guarded, sync_id, creator_id, refresh_profile)
    return sync_id


def run_sync_blocking(sync_id: int, creator_id: int, *, refresh_profile: bool = True) -> float | None:
    """同步主体。返回需要延迟重试的秒数（由调用方在锁外调度）；无重试返回 None。"""
    if store.is_sync_cancelled(sync_id):
        store.update_sync(sync_id, status="cancelled", finished_at=store.now_iso())
        return None
    lock = _creator_lock(creator_id)
    if not lock.acquire(blocking=False):
        store.update_sync(sync_id, status="failed", error="该博主已有同步任务在执行",
                          error_code="conflict", finished_at=store.now_iso())
        return None
    try:
        return _run_sync(sync_id, creator_id, refresh_profile)
    finally:
        lock.release()


def _run_guarded(sync_id: int, creator_id: int, refresh_profile: bool) -> None:
    try:
        retry_delay = run_sync_blocking(sync_id, creator_id, refresh_profile=refresh_profile)
    except Exception as exc:  # 防线程静默死亡
        logger.exception(f"目录同步异常 sync_id={sync_id}")
        store.update_sync(sync_id, status="failed", error=str(exc)[:200],
                          error_code="internal", finished_at=store.now_iso())
        return
    if retry_delay is not None:
        timer = threading.Timer(retry_delay, _executor.submit,
                                args=(_run_guarded, sync_id, creator_id, refresh_profile))
        timer.daemon = True
        timer.start()


def _run_sync(sync_id: int, creator_id: int, refresh_profile: bool) -> float | None:
    client = BilibiliCatalogClient()
    pages_fetched = 0
    sync_row = store.get_sync(sync_id) or {}
    mode = sync_row.get("mode") or "incremental"
    can_short_circuit = mode == "incremental" and store.has_full_catalog_sync(creator_id)
    store.update_sync(sync_id, status="running", started_at=store.now_iso(), error=None,
                      error_code=None)

    def fail(error: CatalogError) -> float | None:
        if store.is_sync_cancelled(sync_id):
            store.update_sync(sync_id, status="cancelled", finished_at=store.now_iso())
            return None
        code = error.code
        retryable, backoffs = _RETRY_POLICY.get(code, (0, []))
        if pages_fetched:
            # 已取得进度后交给手动续跑，防止自动重试不断重置本轮页数限额。
            retryable = 0
        sync = store.get_sync(sync_id) or {}
        retries = int(sync.get("retry_count") or 0)
        if retries < retryable:
            delay = backoffs[min(retries, len(backoffs) - 1)]
            store.update_sync(sync_id, status="queued", retry_count=retries + 1,
                              error=str(error)[:200], error_code=code)
            logger.warning(f"目录同步等待重试 sync_id={sync_id} creator_id={creator_id} code={code} delay={delay}s page={sync.get('page', 0)}")
            return float(delay)
        status = "paused" if code in _PAUSE_CODES or (code == "network" and pages_fetched) else "failed"
        store.update_sync(sync_id, status=status, error=str(error)[:200], error_code=code,
                          finished_at=store.now_iso())
        return None

    def cancelled() -> bool:
        return store.is_sync_cancelled(sync_id)

    try:
        uid = _creator_uid(creator_id)
        client.check_session()
        if refresh_profile:
            try:
                profile = client.profile(uid)
                creator = store.get_creator(creator_id)
                if creator:
                    store.upsert_creator(
                        creator["platform"], creator["uid"],
                        name=profile["name"], avatar=profile["avatar"],
                        follower_count=profile["follower_count"],
                    )
            except CatalogError as error:
                if error.code in _PAUSE_CODES:
                    return fail(error)
                logger.warning(f"刷新博主资料失败（继续同步目录）: {error}")

        sync = store.get_sync(sync_id) or {}
        if mode == "incremental":
            # 增量忽略断点游标：从第 1 页起靠短路提前终止
            page = 1
            found = 0
            added = 0
            known = store.known_bvids(creator_id)
        else:
            page = int(sync.get("page") or 0) + 1
            found = int(sync.get("found") or 0)
            added = int(sync.get("added") or 0)
            known = store.known_bvids(creator_id)
        expected = sync.get("expected")
        previous_signature = None

        while True:
            if cancelled():
                store.update_sync(sync_id, status="cancelled", finished_at=store.now_iso())
                return None
            if pages_fetched >= MAX_PAGES_PER_SYNC:
                raise CatalogError(
                    "budget",
                    f"本次已读取 {MAX_PAGES_PER_SYNC} 页，已暂停并保存进度；"
                    "可稍后手动继续，继续同步仍受 B 站全局请求预算限制",
                )
            entries, total = client.videos(uid, page)
            pages_fetched += 1
            if expected is None and total:
                expected = total
                store.update_sync(sync_id, expected=int(expected))
            # 同页签名防死循环：同一页重复返回说明接口不再翻页
            signature = tuple(entry.get("bvid") for entry in entries)
            if signature and signature == previous_signature:
                raise CatalogError("api", "B 站接口重复返回同一页，同步已停止以免死循环")
            previous_signature = signature

            page_all_known = bool(entries)
            for entry in entries:
                bvid = entry.get("bvid") or ""
                if not bvid:
                    continue
                found += 1
                if is_lesson_entry(entry):
                    # B 站课堂付费课程推广条目：非普通投稿，不入库并清理历史误收
                    store.delete_video_by_bvid(bvid)
                    known.discard(bvid)
                    continue
                is_new = bvid not in known
                if is_new:
                    page_all_known = False
                    known.add(bvid)
                    added += 1
                store.upsert_video(creator_id, {
                    "bvid": bvid,
                    "title": entry.get("title") or "",
                    "cover": entry.get("pic") or "",
                    "description": entry.get("description") or "",
                    "published_at": int(entry.get("created") or 0),
                    "duration": parse_length(entry.get("length")),
                })

            store.update_sync(sync_id, page=page, found=found, added=added)
            if not entries:
                if expected is not None and found < int(expected):
                    raise CatalogError("api", f"投稿目录提前结束：已扫描 {found}/{expected}，请重试深度同步")
                break
            if can_short_circuit and page_all_known:
                # 整页已收录 → 已追平历史，提前终止
                logger.info(f"增量同步短路 creator_id={creator_id} page={page} added={added}")
                break
            if len(entries) < PAGE_SIZE:
                if expected is not None and found < int(expected):
                    raise CatalogError("api", f"投稿目录提前结束：已扫描 {found}/{expected}，请继续深度同步补齐历史投稿")
                break
            if expected is not None and found >= int(expected):
                break
            page += 1

        # 空目录与 expected 不一致时拒绝误判为 complete
        if expected is not None and found == 0 and int(expected) > 0:
            raise CatalogError("api", "投稿目录返回为空，与预期投稿数不一致，未标记为完成")

        if cancelled():
            store.update_sync(sync_id, status="cancelled", finished_at=store.now_iso())
            return None

        creator = store.get_creator(creator_id)
        catalog_total = len(store.known_bvids(creator_id)) or (creator or {}).get("video_count") or 0
        store.touch_creator_synced(creator_id, catalog_total)
        store.update_sync(sync_id, status="complete", finished_at=store.now_iso())
        logger.info(f"目录同步完成 creator_id={creator_id} mode={mode} scanned={found} added={added}")
        return None
    except CatalogError as error:
        logger.warning(f"目录同步失败 creator_id={creator_id} code={error.code}: {error}")
        return fail(error)
    except Exception as error:
        logger.exception(f"目录同步未捕获异常 creator_id={creator_id}")
        store.update_sync(sync_id, status="failed", error=str(error)[:200],
                          error_code="internal", finished_at=store.now_iso())
        return None


def _creator_uid(creator_id: int) -> str:
    creator = store.get_creator(creator_id)
    if not creator:
        raise CatalogError("unavailable", "博主记录不存在")
    return creator["uid"]


def recover_stale_syncs() -> int:
    """启动时清理悬挂的同步状态；interrupted 保留 page 游标，可手动重新同步。"""
    count = store.recover_stale_syncs()
    if count:
        logger.info(f"恢复悬挂的目录同步 {count} 条")
    return count
