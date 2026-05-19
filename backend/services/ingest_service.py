"""视频入库服务 — 编排完整的 URL → 字幕 → AI 处理 → 存储流程。"""

import asyncio
import json
from datetime import datetime
from database import get_db
from core.subtitle import acquire_subtitle, _detect_platform
from core.task_queue import Task, TaskStatus
from core.ai_client import _split_text
from core.logging_config import get_logger

logger = get_logger(__name__)


async def ingest_video(url: str, task: Task = None):
    """完整入库流程。"""

    async def _update_progress(pct: float, msg: str):
        if task:
            task.progress = pct
            task.message = msg

    # 1. 解析视频信息
    await _update_progress(5, "正在解析视频信息...")
    from core.downloader import VideoDownloader
    downloader = VideoDownloader()
    info = await asyncio.get_event_loop().run_in_executor(
        None, downloader.parse_info, url
    )

    platform = _detect_platform(url) or "other"
    video_id = _upsert_video(
        url=url,
        title=info.title,
        platform=platform,
        uploader=info.uploader,
        duration=info.duration,
        thumbnail_url=info.thumbnail,
        description=info.description,
    )

    _update_video_status(video_id, "processing")

    # 2. 获取字幕
    await _update_progress(15, "正在获取字幕...")
    subtitle_result = await acquire_subtitle(url, downloader=downloader)

    if not subtitle_result:
        _update_video_status(video_id, "failed", "无法获取字幕")
        raise Exception("无法获取字幕，该视频可能没有可用的字幕源")

    _save_subtitle(video_id, subtitle_result)
    subtitle_text = subtitle_result.full_text
    video_title = info.title

    # 3. AI 处理
    loop = asyncio.get_event_loop()
    from core import ai_client
    from config import AI_MODEL

    await _update_progress(25, "正在生成 AI 总结...")
    summary = await loop.run_in_executor(
        None, ai_client.summarize, subtitle_text, video_title
    )
    _save_output(video_id, "summary", summary)

    await _update_progress(50, "正在生成思维导图...")
    mindmap = await loop.run_in_executor(
        None, ai_client.generate_mindmap, subtitle_text, video_title
    )
    _save_output(video_id, "mindmap", mindmap)

    await _update_progress(75, "正在生成学习笔记...")
    notes = await loop.run_in_executor(
        None, ai_client.generate_notes, subtitle_text, video_title
    )
    _save_output(video_id, "notes", notes)

    await _update_progress(90, "正在建立知识索引...")
    try:
        from core.vectorstore import add_video_chunks
        chunks = _split_text(subtitle_text, max_chars=500, overlap=50)
        await asyncio.wait_for(
            add_video_chunks(video_id, video_title, chunks),
            timeout=60,
        )
    except Exception as e:
        logger.warning(f"向量化跳过（非致命）: {e}")

    _update_video_status(video_id, "completed")
    return video_id


def _save_output(video_id: int, output_type: str, content):
    from config import AI_MODEL
    with get_db() as conn:
        conn.execute(
            "DELETE FROM ai_outputs WHERE video_id = ? AND output_type = ?",
            (video_id, output_type),
        )
        conn.execute(
            "INSERT INTO ai_outputs (video_id, output_type, content, model_used) VALUES (?, ?, ?, ?)",
            (video_id, output_type, str(content), AI_MODEL),
        )


def _upsert_video(url, title, platform, uploader, duration, thumbnail_url, description) -> int:
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM videos WHERE url = ?", (url,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE videos SET title=?, platform=?, uploader=?, duration=?, thumbnail_url=?, description=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (title, platform, uploader, duration, thumbnail_url, description, existing["id"]),
            )
            return existing["id"]
        cursor = conn.execute(
            "INSERT INTO videos (url, title, platform, uploader, duration, thumbnail_url, description) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (url, title, platform, uploader, duration, thumbnail_url, description),
        )
        # 保持最多 50 条，级联清理关联数据
        old_ids = conn.execute(
            "SELECT id FROM videos WHERE id NOT IN (SELECT id FROM videos ORDER BY created_at DESC LIMIT 50)"
        ).fetchall()
        if old_ids:
            for (vid,) in old_ids:
                conn.execute("DELETE FROM video_tags WHERE video_id = ?", (vid,))
                conn.execute("DELETE FROM subtitles WHERE video_id = ?", (vid,))
            conn.execute("DELETE FROM videos WHERE id NOT IN (SELECT id FROM videos ORDER BY created_at DESC LIMIT 50)")
            conn.execute("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM video_tags)")
        return cursor.lastrowid


def _save_subtitle(video_id: int, result):
    import json
    with get_db() as conn:
        conn.execute("DELETE FROM subtitles WHERE video_id = ?", (video_id,))
        conn.execute(
            "INSERT INTO subtitles (video_id, source, language, full_text, segments_json) VALUES (?, ?, ?, ?, ?)",
            (video_id, result.source, result.language, result.full_text, json.dumps(result.segments, ensure_ascii=False)),
        )


def _update_video_status(video_id: int, status: str, error: str = None):
    with get_db() as conn:
        conn.execute(
            "UPDATE videos SET status=?, error_message=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, error, video_id),
        )
