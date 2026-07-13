"""Application pipeline executed after a Whisper subprocess returns text."""

import asyncio
import json

from core import job_store
from core.auth import add_user_history, log_usage
from core.cache import (
    _max_prompt_version,
    _url_hash,
    save_cache,
    save_video_info_cache,
    save_whisper_cache,
    video_fingerprint,
)
from core.pipeline.mindmap import run_mindmap
from core.pipeline.notes import run_notes
from core.pipeline.qanda import run_qanda
from core.pipeline.subtitle import _build_part_info, save_subtitle
from core.pipeline.subtitle_postprocess import correct_subtitle_text
from core.pipeline.summary import run_summary
from core.pipeline.tags import run_tags
from core.tag_extractor import detect_platform
from core.video import canonical_video_url
from database import get_db


def enqueue_whisper_job(
    *,
    url_hash: str,
    url: str,
    identity: dict,
    lang: str = "",
    estimated_seconds: int = 0,
    info=None,
    fingerprint: str | None = None,
    pipeline: str = "full",
) -> dict:
    info_payload = None
    if info is not None:
        if hasattr(info, "model_dump"):
            info_payload = info.model_dump()
        elif isinstance(info, dict):
            info_payload = info
    task_id = job_store.create_job(
        url_hash,
        url,
        user_id=identity.get("user_id"),
        guest_id=identity.get("guest_id"),
        lang=lang or "",
        estimated_seconds=estimated_seconds,
        payload={
            "pipeline": pipeline,
            "fingerprint": fingerprint,
            "info": info_payload,
        },
    )
    platform = detect_platform(url, (info_payload or {}).get("extractor", ""))
    add_user_history(
        user_id=identity.get("user_id"),
        guest_id=identity.get("guest_id"),
        url_hash=url_hash,
        url=url,
        title=(info_payload or {}).get("title", ""),
        platform=platform,
        status="queued",
    )
    _update_history(identity, url_hash, "queued")
    return job_store.get_job(
        task_id,
        user_id=identity.get("user_id"),
        guest_id=identity.get("guest_id"),
    )


async def finalize_whisper_job(job: dict, worker_result: dict) -> dict:
    raw_text = str(worker_result.get("subtitle_text") or "")
    if len(raw_text.strip()) < 20:
        raise RuntimeError("Whisper 转录结果为空或过短")

    info = await _load_video_info(job)
    canonical_url = canonical_video_url(job["url"], info)
    info.webpage_url = canonical_url
    fingerprint = video_fingerprint(info.extractor, info.id) if info.extractor and info.id else None
    fingerprint = fingerprint or job.get("payload", {}).get("fingerprint")
    save_video_info_cache(canonical_url, info, fingerprint=fingerprint)

    job_store.update_job(job["task_id"], message="正在校正字幕", progress=95)
    corrected = await correct_subtitle_text(
        raw_text,
        info.title or "",
        info.description or "",
        trace_id=job["task_id"][:8],
    )
    language = job.get("lang") or worker_result.get("language") or "auto"
    save_whisper_cache(canonical_url, corrected, language, raw_text, fingerprint=fingerprint)
    save_subtitle(canonical_url, info, corrected, "whisper", language)

    pipeline = job.get("payload", {}).get("pipeline", "full")
    if pipeline == "full":
        result = await asyncio.to_thread(
            _generate_and_persist,
            job,
            info,
            canonical_url,
            corrected,
            fingerprint,
        )
    else:
        result = {
            "subtitle_text": corrected,
            "language": language,
            "source": "whisper",
            "url": canonical_url,
        }

    canonical_hash = _url_hash(canonical_url)
    _replace_history(job, canonical_hash, canonical_url, info.title, info.extractor or "")
    job_store.update_job(job["task_id"], url_hash=canonical_hash, url=canonical_url)
    return result


async def update_terminal_history(job: dict, status: str, error: str | None = None) -> None:
    history_status = "done" if status == "done" else status
    _update_history(job, job.get("url_hash", ""), history_status)


async def _load_video_info(job: dict):
    info_data = job.get("payload", {}).get("info")
    if info_data:
        try:
            from core.models import VideoInfo

            return VideoInfo.model_validate(info_data)
        except Exception:
            pass
    from api.routes import downloader

    return await asyncio.to_thread(downloader.parse_info, job["url"])


def _generate_and_persist(job, info, canonical_url, subtitle_text, fingerprint) -> dict:
    trace_id = job["task_id"][:8]
    result_data = {}
    for event in run_summary(subtitle_text, info.title, trace_id):
        if event.type == "result":
            result_data = event.data

    mindmap_markdown = run_mindmap(subtitle_text, info.title, trace_id)
    notes_text = ""
    for event in run_notes(subtitle_text, info.title, canonical_url, trace_id):
        if event.type == "notes_text":
            notes_text += event.data.get("text", "")

    qa_pairs = []
    for event in run_qanda(subtitle_text, info.title, trace_id):
        if event.type == "qa_pairs":
            qa_pairs = event.data

    result = {
        "result": result_data,
        "mindmap_markdown": mindmap_markdown,
        "notes": notes_text,
        "qa_pairs": qa_pairs,
    }
    platform = detect_platform(canonical_url, info.extractor or "")
    save_cache(
        canonical_url,
        info.title,
        subtitle_text,
        "whisper",
        json.dumps(result, ensure_ascii=False),
        fingerprint=fingerprint,
        part_info=_build_part_info(canonical_url, info=info),
        platform=platform,
        prompt_version=_max_prompt_version(),
    )
    run_tags(canonical_url, info.title, result_data.get("summary", ""), trace_id)
    log_usage(
        user_id=job.get("user_id"),
        guest_id=job.get("guest_id"),
        action="summary",
        status="SUCCESS",
    )
    return result


def _owner_where(identity: dict) -> tuple[str, list]:
    if identity.get("user_id") is not None:
        return "user_id = ?", [identity["user_id"]]
    return "guest_id = ?", [identity.get("guest_id")]


def _update_history(identity: dict, url_hash: str, status: str) -> None:
    owner_sql, owner_params = _owner_where(identity)
    with get_db() as conn:
        conn.execute(
            f"UPDATE user_history SET status = ? WHERE {owner_sql} AND url_hash = ?",
            [status, *owner_params, url_hash],
        )


def _replace_history(job: dict, url_hash: str, url: str, title: str, extractor: str) -> None:
    old_hash = job.get("url_hash", "")
    owner_sql, owner_params = _owner_where(job)
    if old_hash != url_hash:
        with get_db() as conn:
            conn.execute(
                f"DELETE FROM user_history WHERE {owner_sql} AND url_hash = ?",
                [*owner_params, old_hash],
            )
    add_user_history(
        user_id=job.get("user_id"),
        guest_id=job.get("guest_id"),
        url_hash=url_hash,
        url=url,
        title=title,
        platform=detect_platform(url, extractor),
        status="done",
    )
    _update_history(job, url_hash, "done")
