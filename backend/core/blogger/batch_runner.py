"""batch_item 任务处理器：解析 → 字幕 →（必要时）Whisper → AI 生成 → 原子提交。

进程内由 JobScheduler 按 job_type 分发调用；禁止在处理器内 create_job（单槽会死锁），
需要转录时直接以子进程运行 workers/whisper_worker.py。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from core import job_store
from core.auth import add_user_history, check_usage_limit_by_id
from core.background_pipeline import generate_full_from_subtitle
from core.blogger import batches
from core.cache import (
    _url_hash,
    get_cached,
    save_video_info_cache,
    video_fingerprint,
)
from core.features import is_whisper_available
from core.generation_commit import commit_subtitle_generation
from core.job_scheduler import JobCancelled, WorkerFailed
from core.logging_config import get_logger
from core.models import VideoPart, VideoInfo
from core.pipeline.subtitle import (
    BilibiliSubtitleUnavailable,
    _build_part_info,
    fetch_subtitle,
)
from core.pipeline.subtitle_postprocess import correct_subtitle_text
from core.tag_extractor import detect_platform
from core.video import canonical_video_url

logger = get_logger("blogger.batch_runner")


def _set_phase(job: dict, item_id: str | None, phase: str, message: str, progress: float) -> None:
    job_store.update_job(job["task_id"], message=message, progress=progress)
    if item_id:
        batches.update_item(item_id, phase=phase, status="running")


def _check_cancel(job: dict) -> None:
    if job_store.is_cancel_requested(job["task_id"]):
        raise JobCancelled()


def _snapshot_info(payload_info: dict | None, url: str, bvid: str = "", cid=None, part_index: int = 1) -> VideoInfo:
    """用目录快照构造最小 VideoInfo（快路径，省掉 yt-dlp 解析）。"""
    data = payload_info or {}
    parts = []
    for part in data.get("parts") or []:
        parts.append(VideoPart(
            index=int(part.get("index") or 1),
            title=part.get("title") or "",
            cid=part.get("cid"),
            duration=part.get("duration"),
        ))
    if cid and not any(p.cid == cid for p in parts):
        parts.insert(0, VideoPart(index=part_index, title=f"P{part_index}", cid=cid))
    return VideoInfo(
        title=data.get("title") or "",
        webpage_url=url,
        id=bvid or data.get("id"),
        duration=data.get("duration"),
        extractor="bilibili",
        parts=parts,
    )


def _complete_cache(cached):
    from core.content_state import decode_payload
    from core.learning import complete_payload, artifact_states
    payload = decode_payload(cached.get("result_json"))
    return complete_payload(payload) and not any(s["stale"] for s in artifact_states(payload, cached.get("subtitle_text", "")).values())


async def run_batch_item(job: dict, scheduler) -> dict:
    payload = job.get("payload") or {}
    item_id = payload.get("batch_item_id")
    mode = payload.get("mode") or "full"
    url = job["url"]
    identity = {"user_id": job.get("user_id"), "guest_id": job.get("guest_id")}

    # ── 0. 缓存命中：直接复用，不耗额度 ──
    cached = get_cached(url)
    if cached and cached.get("result_json") and _complete_cache(cached):
        if mode == "full":
            _set_phase(job, item_id, "reused", "命中已有学习资料，跳过生成", 100)
            add_user_history(
                user_id=identity["user_id"], guest_id=identity["guest_id"],
                url_hash=_url_hash(url), url=url,
                title=cached.get("video_title") or "", platform="bilibili", status="done",
            )
            if item_id:
                batches.update_item(item_id, status="done")
            return {"reused": True, "url": url}

    _check_cancel(job)

    # ── 1. 元数据：快路径优先，缺失才走 yt-dlp ──
    _set_phase(job, item_id, "meta", "解析视频信息", 20)
    info = None
    if payload.get("info") and payload.get("bvid"):
        info = _snapshot_info(payload.get("info"), url, payload.get("bvid", ""),
                              payload.get("cid"), int(payload.get("part_index") or 1))
        info.webpage_url = canonical_video_url(url, info)
    if info is None:
        info = await asyncio.to_thread(_parse_info, url)
        info.webpage_url = canonical_video_url(url, info)
    canonical_url = info.webpage_url
    fingerprint = video_fingerprint(info.extractor, info.id) if info.extractor and info.id else None

    cached = get_cached(canonical_url, fingerprint)
    if cached and cached.get("result_json") and mode == "full" and _complete_cache(cached):
        _set_phase(job, item_id, "reused", "命中已有学习资料，跳过生成", 100)
        add_user_history(
            user_id=identity["user_id"], guest_id=identity["guest_id"],
            url_hash=_url_hash(canonical_url), url=canonical_url,
            title=info.title, platform=detect_platform(canonical_url, info.extractor or ""),
            status="done",
        )
        if item_id:
            batches.update_item(item_id, status="done")
        return {"reused": True, "url": canonical_url}

    save_video_info_cache(canonical_url, info, fingerprint)
    if mode == "meta":
        _set_phase(job, item_id, "meta", "解析完成", 100)
        return {"url": canonical_url, "title": info.title, "meta_only": True}

    _check_cancel(job)

    # ── 2. 字幕：缓存 → B 站 CC（cid 精确）→ yt-dlp ──
    _set_phase(job, item_id, "subtitle", "获取字幕", 45)
    try:
        subtitle_text, source, language = await fetch_subtitle(
            canonical_url, info, fingerprint=fingerprint, trace_id=job["task_id"][:8],
        )
    except BilibiliSubtitleUnavailable as error:
        raise RuntimeError(str(error)) from error

    whisper_raw = None
    if not subtitle_text:
        if not is_whisper_available():
            raise RuntimeError("没有可用字幕且本地 Whisper 不可用，无法处理该视频")
        _check_cancel(job)
        # Whisper 需要音频直链避免 412：快路径没有直链时补一次解析
        if not info.audio_stream_url:
            refreshed = await asyncio.to_thread(_parse_info, canonical_url)
            refreshed.webpage_url = canonical_url
            info = refreshed
            save_video_info_cache(canonical_url, info, fingerprint)
        _set_phase(job, item_id, "whisper", "本地转录中", 60)
        worker_result = await _run_whisper(job, scheduler, info)
        whisper_raw = str(worker_result.get("subtitle_text") or "")
        if len(whisper_raw.strip()) < 20:
            raise RuntimeError("Whisper 转录结果为空或过短")
        job_store.update_job(job["task_id"], message="正在校正字幕", progress=80)
        subtitle_text = await correct_subtitle_text(
            whisper_raw, info.title or "", info.description or "", trace_id=job["task_id"][:8],
        )
        source, language = "whisper", (job.get("lang") or worker_result.get("language") or "auto")

    if not subtitle_text or len(subtitle_text.strip()) < 20:
        raise RuntimeError("字幕内容为空或过短")

    platform = detect_platform(canonical_url, info.extractor or "")
    part_info = _build_part_info(canonical_url, info=info)

    if mode == "subtitle":
        commit_subtitle_generation(
            url=canonical_url,
            info=info,
            fingerprint=fingerprint,
            subtitle_text=subtitle_text,
            subtitle_source=source,
            subtitle_language=language or "auto",
            part_info=part_info,
            platform=platform,
            whisper_raw_text=whisper_raw or "",
        )
        add_user_history(
            user_id=identity["user_id"], guest_id=identity["guest_id"],
            url_hash=_url_hash(canonical_url), url=canonical_url,
            title=info.title, platform=platform, status="done",
        )
        _set_phase(job, item_id, "subtitle", "字幕就绪", 100)
        return {"url": canonical_url, "source": source, "subtitle_only": True}

    # ── 3. AI 生成前额度闸门 ──
    allowed, used, limit = check_usage_limit_by_id(identity["user_id"], identity["guest_id"])
    if not allowed:
        if item_id:
            batches.pause_batch_for_usage_limit(payload.get("batch_id") or "", item_id)
        return {"skipped": "usage_limit", "used": used, "limit": limit, "url": canonical_url}

    _check_cancel(job)

    # ── 4. 完整 AI 学习资料（摘要/思维导图/笔记/问答）──
    _set_phase(job, item_id, "ai", "生成 AI 学习资料", 85)
    result = await asyncio.to_thread(
        generate_full_from_subtitle,
        job,
        info=info,
        canonical_url=canonical_url,
        subtitle_text=subtitle_text,
        subtitle_source=source,
        subtitle_language=language or "auto",
        fingerprint=fingerprint,
        raw_text=whisper_raw,
    )
    if item_id:
        batches.update_item(item_id, status="done")
    return {"url": canonical_url, "source": source, "result_keys": sorted(result.keys())}


def _parse_info(url: str):
    from api.routes import downloader
    return downloader.parse_info(url)


async def _run_whisper(job: dict, scheduler, info: VideoInfo) -> dict:
    result_path = Path(scheduler.work_dir) / f"{job['task_id']}.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.unlink(missing_ok=True)
    whisper_job = {
        "task_id": job["task_id"],
        "url": job["url"],
        "lang": job.get("lang") or "",
        "payload": {"info": info.model_dump() if hasattr(info, "model_dump") else {}},
    }
    command = scheduler._default_command(whisper_job, result_path)
    try:
        return await scheduler.run_worker_subprocess(job["task_id"], command)
    except WorkerFailed as exc:
        raise RuntimeError(f"Whisper 转录失败: {exc}") from exc
    finally:
        result_path.unlink(missing_ok=True)
