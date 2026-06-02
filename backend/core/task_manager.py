"""后台转录任务管理器。

使用 asyncio.create_task() 在后台执行 Whisper 转录 + AI 流水线。
内存中维护任务状态字典，进程重启时自动清理。
"""

import asyncio
import time
import uuid

from core.logging_config import get_logger

logger = get_logger(__name__)

# ─── 内存任务存储 ───

_tasks: dict[str, dict] = {}
# asyncio.Task 引用，用于真正取消正在运行的任务
_async_tasks: dict[str, asyncio.Task] = {}

# 任务超时：30 分钟
_TASK_TIMEOUT = 30 * 60


def create_task(url_hash: str, url: str, identity: dict, lang: str,
                estimated_seconds: int, info=None, fingerprint: str = None) -> str:
    """创建后台任务，返回 task_id。"""
    task_id = uuid.uuid4().hex[:12]
    _tasks[task_id] = {
        "task_id": task_id,
        "url_hash": url_hash,
        "url": url,
        "user_id": identity.get("user_id"),
        "guest_id": identity.get("guest_id"),
        "lang": lang,
        "fingerprint": fingerprint,
        "stage": "downloading",
        "estimated_seconds": estimated_seconds,
        "started_at": time.time(),
        "status": "running",
        "error": None,
        # 保存 info 的序列化字段，后台任务需要
        "_info_title": getattr(info, "title", "") if info else "",
        "_info_description": getattr(info, "description", "") if info else "",
        "_info_extractor": getattr(info, "extractor", "") if info else "",
        "_info_duration": getattr(info, "duration", 0) if info else 0,
    }
    logger.info(f"后台任务创建 task_id={task_id} url_hash={url_hash} est={estimated_seconds}s")
    return task_id


def get_task(task_id: str) -> dict | None:
    """获取单个任务状态。"""
    task = _tasks.get(task_id)
    if not task:
        return None
    # 检查超时
    if task["status"] == "running" and time.time() - task["started_at"] > _TASK_TIMEOUT:
        task["status"] = "failed"
        task["error"] = "任务超时（30分钟）"
        logger.warning(f"后台任务超时 task_id={task_id}")
    return _strip_internal(task)


def get_active_tasks(user_id: int = None, guest_id: str = None) -> list[dict]:
    """获取当前用户的所有活跃任务。"""
    now = time.time()
    result = []
    for task in _tasks.values():
        # 用户匹配
        if user_id and task.get("user_id") == user_id:
            pass
        elif guest_id and task.get("guest_id") == guest_id:
            pass
        else:
            continue
        # 超时检查
        if task["status"] == "running" and now - task["started_at"] > _TASK_TIMEOUT:
            task["status"] = "failed"
            task["error"] = "任务超时（30分钟）"
        if task["status"] == "running":
            result.append(_strip_internal(task))
    return result


def update_task(task_id: str, **kwargs):
    """更新任务字段。"""
    task = _tasks.get(task_id)
    if task:
        task.update(kwargs)


def remove_task(task_id: str):
    """移除任务（同时取消正在运行的 asyncio Task）。"""
    _tasks.pop(task_id, None)
    at = _async_tasks.pop(task_id, None)
    if at and not at.done():
        at.cancel()


def has_active_task(url_hash: str) -> str | None:
    """检查是否有针对该 url_hash 的活跃任务，返回 task_id 或 None。"""
    now = time.time()
    for task in _tasks.values():
        if task["url_hash"] == url_hash and task["status"] == "running":
            if now - task["started_at"] > _TASK_TIMEOUT:
                task["status"] = "failed"
                task["error"] = "任务超时（30分钟）"
                continue
            return task["task_id"]
    return None


def _strip_internal(task: dict) -> dict:
    """移除内部字段，返回给前端。"""
    return {k: v for k, v in task.items() if not k.startswith("_")}


# ─── 后台执行 ───

async def run_background_task(task_id: str):
    """后台执行完整流水线：Whisper 转录 → AI 校正 → 摘要/导图/笔记/问答 → 持久化。"""
    task = _tasks.get(task_id)
    if not task:
        return

    url = task["url"]
    lang = task.get("lang")
    identity = {
        "user_id": task.get("user_id"),
        "guest_id": task.get("guest_id"),
    }
    trace_id = task_id[:8]

    # 保存 asyncio.Task 引用，支持真正取消
    _async_tasks[task_id] = asyncio.current_task()

    try:
        from core.whisper import transcribe_video_async
        from core.pipeline.subtitle_postprocess import correct_subtitle_text
        from core.pipeline.subtitle import save_subtitle, _build_part_info
        from core.cache import _url_hash
        from api.routes import downloader

        # ── 1. 解析视频信息 ──
        update_task(task_id, stage="parsing")
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, downloader.parse_info, url)

        # 计算 canonical url_hash（与 add_user_history 一致）
        canonical_url = info.webpage_url or url
        canonical_hash = _url_hash(canonical_url)

        # ── 2. 字幕获取（四级降级：DB → B站CC → yt-dlp → Whisper） ──
        update_task(task_id, stage="transcribing")
        from core.pipeline.subtitle import fetch_subtitle
        sub_result = await loop.run_in_executor(None, fetch_subtitle, canonical_url, info, lang)
        subtitle_text = sub_result.get("text") if sub_result else None
        sub_source = sub_result.get("source", "whisper") if sub_result else "whisper"

        if not subtitle_text or len(subtitle_text.strip()) < 20:
            update_task(task_id, status="failed", error="Whisper 转录结果为空")
            _update_db_status(canonical_hash, "failed")
            return

        # ── 3. AI 校正 ──
        update_task(task_id, stage="correcting")
        subtitle_text = await correct_subtitle_text(
            subtitle_text, info.title, info.description or "", trace_id=trace_id
        )

        # 保存字幕
        from core.tag_extractor import detect_platform
        from core.cache import save_video_info_cache, video_fingerprint

        fp = video_fingerprint(info.extractor, info.id) if info.extractor and info.id else None
        save_video_info_cache(canonical_url, info, fingerprint=fp)
        save_subtitle(canonical_url, info, subtitle_text, sub_source, lang or "auto")

        # ── 4. AI 流水线 ──
        update_task(task_id, stage="generating")

        from core.pipeline.summary import run_summary
        from core.pipeline.mindmap import run_mindmap
        from core.pipeline.notes import run_notes
        from core.pipeline.qanda import run_qanda
        from core.pipeline.tags import run_tags
        from core.cache import save_cache, _max_prompt_version, _url_hash
        from core.auth import log_usage, add_user_history

        result_data = {}
        for event in run_summary(subtitle_text, info.title, trace_id):
            if event.type == "result":
                result_data = event.data

        mindmap_md = run_mindmap(subtitle_text, info.title, trace_id)

        notes_text = ""
        for event in run_notes(subtitle_text, info.title, canonical_url, trace_id):
            if event.type == "notes_text":
                notes_text += event.data.get("text", "")

        qa_pairs_result = []
        for event in run_qanda(subtitle_text, info.title, trace_id):
            if event.type == "qa_pairs":
                qa_pairs_result = event.data

        # ── 5. 持久化 ──
        import json
        platform_name = detect_platform(canonical_url, info.extractor or "")
        save_cache(
            canonical_url, info.title, subtitle_text, "whisper",
            json.dumps({
                "result": result_data,
                "mindmap_markdown": mindmap_md,
                "notes": notes_text,
                "qa_pairs": qa_pairs_result,
            }, ensure_ascii=False),
            fingerprint=fp,
            part_info=_build_part_info(canonical_url, info=info),
            platform=platform_name,
            prompt_version=_max_prompt_version(),
        )

        # 用 canonical_hash 更新，与 fast-path 创建的记录一致
        add_user_history(
            user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
            url_hash=canonical_hash, url=canonical_url,
            title=info.title, platform=platform_name,
        )
        _update_db_status(canonical_hash, "done")

        # 更新 task 内存中的 url_hash（canonical），保持一致性
        task["url_hash"] = canonical_hash

        summary_for_tags = result_data.get("summary", "")
        run_tags(canonical_url, info.title, summary_for_tags, trace_id)

        log_usage(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
                  action="summary", status="SUCCESS")

        update_task(task_id, status="done")
        logger.info(f"后台任务完成 task_id={task_id}")

    except asyncio.CancelledError:
        logger.info(f"后台任务被取消 task_id={task_id}")
        update_task(task_id, status="failed", error="用户取消")
        # 用当前的 url_hash（可能已更新为 canonical）
        _update_db_status(task.get("url_hash", ""), "failed")
    except Exception as e:
        logger.error(f"后台任务失败 task_id={task_id}: {e}")
        update_task(task_id, status="failed", error=str(e))
        _update_db_status(task.get("url_hash", ""), "failed")
    finally:
        _async_tasks.pop(task_id, None)
        await asyncio.sleep(60)
        remove_task(task_id)


def _update_db_status(url_hash: str, status: str):
    """更新 user_history 表中的 status 字段。"""
    try:
        from database import get_db
        with get_db() as conn:
            conn.execute(
                "UPDATE user_history SET status = ? WHERE url_hash = ?",
                (status, url_hash)
            )
    except Exception as e:
        logger.warning(f"更新 history status 失败: {e}")
