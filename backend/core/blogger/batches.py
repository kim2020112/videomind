"""博主批量任务：选择快照冻结、条目入队、动作与终态回写。

每个条目对应一个 background_jobs 行（job_type="batch_item"），
队列位置/取消/恢复复用 job_store；条目状态与批次计数写回 blogger_batch_* 表。
"""

from __future__ import annotations

import json
import uuid

from core import job_store
from core.auth import add_user_history
from core.blogger import store
from core.blogger.catalog import BilibiliCatalogClient, CatalogError
from core.cache import _url_hash
from core.logging_config import get_logger
from core.tag_extractor import detect_platform
from database import get_db

logger = get_logger("blogger.batches")

BATCH_MODES = ("full", "subtitle", "meta")
MAX_BATCH_ITEMS = 200

ITEM_TERMINAL = ("done", "failed", "skipped", "cancelled")

# 条目状态：queued|running|done|failed|skipped|cancelled|paused
# phase：meta|subtitle|whisper|ai|reused|''


def _now() -> str:
    from core.blogger.store import now_iso
    return now_iso()


def part_url(bvid: str, page: int) -> str:
    return f"https://www.bilibili.com/video/{bvid}" + (f"?p={page}" if page and page > 1 else "")


def create_batch(creator_id: int, selection: dict, *, mode: str, identity: dict) -> dict:
    """冻结选择快照并为每个分 P 入队 batch_item job。"""
    if mode not in BATCH_MODES:
        raise ValueError(f"mode 必须是 {'/'.join(BATCH_MODES)} 之一")
    video_ids = [int(v) for v in (selection.get("video_ids") or [])]
    if not video_ids:
        raise ValueError("请至少选择一个投稿")
    include_all_parts = bool(selection.get("include_all_parts", True))
    exclude = {str(x) for x in (selection.get("exclude_part_ids") or [])}

    # 展开分 P 并冻结快照（未加载过分 P 的视频补一次 view 接口）
    client = BilibiliCatalogClient()
    entries: list[dict] = []
    for video_id in video_ids:
        video = store.get_video(video_id)
        if not video or video["creator_id"] != creator_id:
            raise ValueError("所选投稿不属于该博主")
        if not store.has_pages(video_id):
            try:
                view_data, pages = client.parts(video["bvid"])
            except CatalogError as error:
                raise ValueError(f"展开分 P 失败（{video['bvid']}）：{error}") from error
            store.replace_pages(video_id, [
                {
                    "cid": page.get("cid"),
                    "page": page.get("page") or index + 1,
                    "part_title": page.get("part") or "",
                    "duration": page.get("duration") or 0,
                }
                for index, page in enumerate(pages)
            ])
        rows = store.list_pages(video_id)
        if not rows:
            raise ValueError(f"视频 {video['bvid']} 未返回分 P 信息")
        for row in rows:
            key = f"{video_id}:{row['page']}"
            if key in exclude:
                continue
            if not include_all_parts and row["page"] != 1:
                continue
            entries.append({
                "video_id": video_id,
                "bvid": video["bvid"],
                "cid": row["cid"],
                "page": row["page"],
                "title": video.get("title") or "",
                "part_title": row.get("part_title") or "",
                "duration": row.get("duration") or 0,
            })
    if not entries:
        raise ValueError("筛选后没有可处理的分 P")
    if len(entries) > MAX_BATCH_ITEMS:
        raise ValueError(f"单批最多 {MAX_BATCH_ITEMS} 条，当前 {len(entries)} 条，请分批处理")

    batch_id = uuid.uuid4().hex
    now = _now()
    pending: list[tuple[str, dict]] = []
    with get_db() as conn:
        conn.execute(
            "INSERT INTO blogger_batches (id, user_id, guest_id, creator_id, mode, selection_json, "
            "status, total, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)",
            (
                batch_id,
                identity.get("user_id"),
                identity.get("guest_id"),
                creator_id,
                mode,
                json.dumps(selection, ensure_ascii=False),
                len(entries),
                now,
                now,
            ),
        )
        for position, entry in enumerate(entries):
            url = part_url(entry["bvid"], entry["page"])
            item_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO blogger_batch_items (id, batch_id, position, url, url_hash, bvid, cid, "
                "part_index, title, status, phase, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', '', ?, ?)",
                (
                    item_id, batch_id, position, url, _url_hash(url), entry["bvid"],
                    entry["cid"], entry["page"],
                    entry["title"] + (f" · {entry['part_title']}" if entry["part_title"] else ""),
                    now, now,
                ),
            )
            pending.append((item_id, {**entry, "url": url}))

    # 入队 job 会开自己的数据库连接，必须放在批次写事务提交之后
    identity_owner = {"user_id": identity.get("user_id"), "guest_id": identity.get("guest_id")}
    for item_id, entry in pending:
        job = _enqueue_item_job(item_id, batch_id, entry, mode, entry["url"], identity_owner)
        update_item(item_id, job_id=job["task_id"])
    return get_batch(batch_id, identity) or {}


def _enqueue_item_job(item_id: str, batch_id: str, entry: dict, mode: str,
                      url: str, identity: dict) -> dict:
    payload = {
        "batch_id": batch_id,
        "batch_item_id": item_id,
        "mode": mode,
        "bvid": entry["bvid"],
        "cid": entry["cid"],
        "part_index": entry["page"],
        "info": {
            "title": entry["title"],
            "webpage_url": f"https://www.bilibili.com/video/{entry['bvid']}",
            "id": entry["bvid"],
            "extractor": "bilibili",
            "duration": entry["duration"],
            "parts": [{
                "index": entry["page"],
                "title": entry["part_title"] or f"P{entry['page']}",
                "cid": entry["cid"],
                "duration": entry["duration"],
            }],
        },
    }
    job = job_store.create_job(
        _url_hash(url),
        url,
        user_id=identity.get("user_id"),
        guest_id=identity.get("guest_id"),
        estimated_seconds=int(entry.get("duration") or 0) // 2 or 120,
        payload=payload,
        job_type="batch_item",
    )
    if isinstance(job, dict):
        task_id = job["task_id"]
    else:
        task_id = job
        job = job_store.get_job(task_id, user_id=identity.get("user_id"),
                                guest_id=identity.get("guest_id"))
    # create_job 同 owner+url_hash 去重可能复用既有任务：回填批次标记保证终态回写
    existing_payload = (job or {}).get("payload") or {}
    if existing_payload.get("batch_item_id") != item_id:
        merged = {**existing_payload, **payload}
        job_store.update_job(task_id, payload=merged)
    platform = detect_platform(url, "bilibili")
    add_user_history(
        user_id=identity.get("user_id"),
        guest_id=identity.get("guest_id"),
        url_hash=_url_hash(url),
        url=url,
        title=payload["info"]["title"],
        platform=platform,
        status="queued",
    )
    return {"task_id": task_id}


# ── 查询 ──

def get_batch(batch_id: str, identity: dict | None = None) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM blogger_batches WHERE id = ?", (batch_id,)
        ).fetchone()
        if row is None:
            return None
        batch = dict(row)
        if identity is not None:
            if identity.get("user_id") and batch.get("user_id") != identity.get("user_id"):
                return None
            if not identity.get("user_id") and batch.get("guest_id") != identity.get("guest_id"):
                return None
        items = conn.execute(
            "SELECT * FROM blogger_batch_items WHERE batch_id = ? ORDER BY position",
            (batch_id,),
        ).fetchall()
        batch["items"] = [dict(item) for item in items]
        batch["selection"] = json.loads(batch.get("selection_json") or "{}")
        return batch


def list_batches(creator_id: int, identity: dict, *, limit: int = 20) -> list[dict]:
    if identity.get("user_id"):
        owner_sql, owner_params = "user_id = ?", [identity["user_id"]]
    else:
        owner_sql, owner_params = "guest_id = ?", [identity["guest_id"]]
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM blogger_batches WHERE creator_id = ? AND " + owner_sql +
            " ORDER BY created_at DESC, id DESC LIMIT ?",
            [creator_id, *owner_params, max(1, min(int(limit), 100))],
        ).fetchall()
        return [dict(row) for row in rows]


# ── 状态写回 ──

def update_item(item_id: str, **changes) -> None:
    allowed = {"status", "phase", "error", "error_code", "job_id", "retry_count"}
    fields = {key: value for key, value in changes.items() if key in allowed}
    if not fields:
        return
    fields["updated_at"] = _now()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    with get_db() as conn:
        conn.execute(
            f"UPDATE blogger_batch_items SET {assignments} WHERE id = ?",
            [*fields.values(), item_id],
        )


def item_for_job(job: dict) -> dict | None:
    items = items_for_job(job)
    return items[0] if items else None


def items_for_job(job: dict) -> list[dict]:
    """job 关联的全部条目：payload 标记 + job_id 命中。

    同 owner+url_hash 去重复用 job 时，多个批次的条目共享同一 job_id，
    终态回写必须逐条处理，否则先入批次的条目会永久悬挂。
    """
    payload = (job or {}).get("payload") or {}
    item_id = payload.get("batch_item_id") or ""
    task_id = (job or {}).get("task_id")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM blogger_batch_items WHERE id = ? OR (job_id = ? AND job_id != '')",
            (item_id, task_id),
        ).fetchall()
        return [dict(row) for row in rows]


def resolve_item_for_job(job: dict, status: str, error: str | None = None) -> None:
    """job 终态回写条目状态与批次计数。job_id 命中即幂等。"""
    items = items_for_job(job)
    if not items:
        return
    mapping = {"done": "done", "failed": "failed", "cancelled": "cancelled"}
    item_status = mapping.get(status)
    for item in items:
        if item_status is None or item["status"] in ITEM_TERMINAL or item["status"] == "paused":
            # 已有终态（如 skipped）或用户暂停的条目不被覆盖
            _refresh_batch(item["batch_id"])
            continue
        update_item(item["id"], status=item_status,
                    error=(error or "")[:200] if item_status == "failed" else item.get("error"))
        _refresh_batch(item["batch_id"])


def _refresh_batch(batch_id: str) -> None:
    with get_db() as conn:
        counts = conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN status IN ('done', 'skipped') THEN 1 ELSE 0 END) AS finished, "
            "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed, "
            "SUM(CASE WHEN status IN ('queued', 'running') THEN 1 ELSE 0 END) AS active "
            "FROM blogger_batch_items WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        status_row = conn.execute(
            "SELECT status FROM blogger_batches WHERE id = ?", (batch_id,)
        ).fetchone()
        if not status_row or not counts:
            return
        current = status_row["status"]
        if current in ("cancelled", "paused"):
            conn.execute(
                "UPDATE blogger_batches SET done_count = ?, failed_count = ?, updated_at = ? WHERE id = ?",
                (counts["finished"] or 0, counts["failed"] or 0, _now(), batch_id),
            )
            return
        if (counts["active"] or 0) == 0:
            final = "done" if (counts["failed"] or 0) == 0 else "failed"
        else:
            final = "running"
        conn.execute(
            "UPDATE blogger_batches SET status = ?, done_count = ?, failed_count = ?, updated_at = ? WHERE id = ?",
            (final, counts["finished"] or 0, counts["failed"] or 0, _now(), batch_id),
        )


def pause_batch_for_usage_limit(batch_id: str, item_id: str) -> None:
    """额度耗尽：当前条目标 skipped，剩余排队条目转 paused，批次暂停。"""
    with get_db() as conn:
        conn.execute(
            "UPDATE blogger_batch_items SET status = 'skipped', error_code = 'usage_limit', "
            "error = '今日 AI 额度已用完', updated_at = ? WHERE id = ?",
            (_now(), item_id),
        )
        conn.execute(
            "UPDATE blogger_batch_items SET status = 'paused', updated_at = ? "
            "WHERE batch_id = ? AND status = 'queued'",
            (_now(), batch_id),
        )
        conn.execute(
            "UPDATE blogger_batches SET status = 'paused', error = '今日 AI 额度已用完，批次已暂停', "
            "updated_at = ? WHERE id = ?",
            (_now(), batch_id),
        )
        _refresh_batch_counts(conn, batch_id)


def _refresh_batch_counts(conn, batch_id: str) -> None:
    counts = conn.execute(
        "SELECT SUM(CASE WHEN status IN ('done', 'skipped') THEN 1 ELSE 0 END) AS finished, "
        "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed "
        "FROM blogger_batch_items WHERE batch_id = ?",
        (batch_id,),
    ).fetchone()
    conn.execute(
        "UPDATE blogger_batches SET done_count = ?, failed_count = ?, updated_at = ? WHERE id = ?",
        (counts["finished"] or 0, counts["failed"] or 0, _now(), batch_id),
    )


# ── 动作 ──

def batch_action(batch_id: str, action: str, identity: dict) -> dict:
    batch = get_batch(batch_id, identity)
    if not batch:
        raise ValueError("批次不存在")
    owner = {"user_id": batch.get("user_id"), "guest_id": batch.get("guest_id")}

    if action == "cancel":
        for item in batch["items"]:
            if item.get("job_id"):
                job_store.request_cancel(item["job_id"], **owner)
            if item["status"] not in ITEM_TERMINAL:
                update_item(item["id"], status="cancelled")
        with get_db() as conn:
            conn.execute(
                "UPDATE blogger_batches SET status = 'cancelled', updated_at = ? WHERE id = ?",
                (_now(), batch_id),
            )
    elif action == "pause":
        for item in batch["items"]:
            if item.get("job_id"):
                job_store.request_cancel(item["job_id"], **owner)
            if item["status"] not in ITEM_TERMINAL:
                update_item(item["id"], status="paused")
        with get_db() as conn:
            conn.execute(
                "UPDATE blogger_batches SET status = 'paused', updated_at = ? WHERE id = ?",
                (_now(), batch_id),
            )
    elif action == "resume":
        if batch["status"] != "paused":
            raise ValueError("只有暂停的批次可以恢复")
        for item in batch["items"]:
            # 额度暂停时排队 job 会继续空转并把条目记为 skipped+usage_limit，
            # 两类都要恢复，否则恢复动作会漏掉大部分条目
            if item["status"] == "paused" or (
                item["status"] == "skipped" and item.get("error_code") == "usage_limit"
            ):
                _requeue_item(item, owner, reset_retry=False)
        with get_db() as conn:
            conn.execute(
                "UPDATE blogger_batches SET status = 'queued', error = NULL, updated_at = ? WHERE id = ?",
                (_now(), batch_id),
            )
        _refresh_batch(batch_id)
    elif action == "retry_failed":
        retried = 0
        for item in batch["items"]:
            if item["status"] == "failed" and int(item.get("retry_count") or 0) < 2:
                _requeue_item(item, owner, reset_retry=True)
                retried += 1
        if retried == 0:
            raise ValueError("没有可重试的失败条目（最多重试 2 次）")
        with get_db() as conn:
            conn.execute(
                "UPDATE blogger_batches SET status = 'queued', error = NULL, updated_at = ? WHERE id = ?",
                (_now(), batch_id),
            )
        _refresh_batch(batch_id)
    else:
        raise ValueError(f"未知动作: {action}")
    return get_batch(batch_id, identity) or {}


def _requeue_item(item: dict, owner: dict, *, reset_retry: bool) -> None:
    changes = {"status": "queued", "phase": "", "error": None, "error_code": None, "job_id": None}
    if reset_retry:
        changes["retry_count"] = int(item.get("retry_count") or 0) + 1
    update_item(item["id"], **changes)
    entry = {
        "bvid": item["bvid"],
        "cid": item["cid"],
        "page": item["part_index"] or 1,
        "title": item.get("title") or "",
        "part_title": "",
        "duration": 0,
    }
    mode = "full"
    with get_db() as conn:
        row = conn.execute("SELECT mode FROM blogger_batches WHERE id = ?", (item["batch_id"],)).fetchone()
        if row:
            mode = row["mode"]
    job = _enqueue_item_job(item["id"], item["batch_id"], entry, mode, item["url"], owner)
    update_item(item["id"], job_id=job["task_id"])


def reconcile_batches() -> int:
    """启动恢复：补齐悬挂批次的条目任务，修正无活跃任务的 running 条目。"""
    fixed = 0
    with get_db() as conn:
        batches = conn.execute(
            "SELECT * FROM blogger_batches WHERE status IN ('queued', 'running')"
        ).fetchall()
    for row in batches:
        batch = get_batch(row["id"])
        if not batch:
            continue
        owner = {"user_id": batch.get("user_id"), "guest_id": batch.get("guest_id")}
        for item in batch["items"]:
            if item["status"] in ITEM_TERMINAL:
                continue
            job = job_store.get_job(item["job_id"], **owner) if item.get("job_id") else None
            active = job and job["status"] not in job_store.TERMINAL_STATUSES
            if not active:
                _requeue_item(item, owner, reset_retry=False)
                fixed += 1
        _refresh_batch(row["id"])
    if fixed:
        logger.info(f"批次启动恢复：补队 {fixed} 个条目")
    return fixed
