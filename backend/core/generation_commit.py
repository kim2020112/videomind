"""Validated, atomic persistence for generated learning artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from core.cache import _cleanup_old_cache, _compute_notes_chars, _url_hash
from database import get_db


class InvalidGenerationResult(ValueError):
    """Raised before persistence when generated output is incomplete or invalid."""


def validate_summary_result(result: Any) -> dict:
    if not isinstance(result, dict):
        raise InvalidGenerationResult("AI summary result must be an object")
    summary = result.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise InvalidGenerationResult("AI summary result is empty")
    if result.get("is_partial") is True:
        raise InvalidGenerationResult("AI summary did not reach a complete result")
    _encode_json(result, "AI summary result")
    return result


def commit_full_generation(
    *,
    url: str,
    info,
    fingerprint: str | None,
    subtitle_text: str,
    subtitle_source: str,
    subtitle_language: str,
    part_info: str,
    platform: str,
    result: dict,
    prompt_version: int,
    user_id: int | None,
    guest_id: str | None,
    whisper_raw_text: str | None = None,
) -> str:
    """Validate and replace all records for a successful full generation."""
    subtitle_text = _require_text(subtitle_text, "subtitle")
    result_payload = _validate_full_payload(result)
    result_json = _encode_json(result_payload, "generation result")
    info_dict, info_json = _normalize_info(info)
    now = _cache_timestamp()
    url_hash = _url_hash(url)
    video_title = str(info_dict.get("title") or "")

    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _upsert_video_info(
            conn,
            url_hash=url_hash,
            url=url,
            fingerprint=fingerprint,
            info=info_dict,
            info_json=info_json,
            now=now,
        )
        _replace_video_subtitle(
            conn,
            url=url,
            info=info_dict,
            platform=platform,
            part_info=part_info,
            subtitle_text=subtitle_text,
            subtitle_source=subtitle_source,
            subtitle_language=subtitle_language,
        )
        if whisper_raw_text is not None:
            _upsert_whisper(
                conn,
                url_hash=url_hash,
                url=url,
                fingerprint=fingerprint,
                subtitle_text=subtitle_text,
                language=subtitle_language,
                raw_text=str(whisper_raw_text),
                now=now,
            )
        _upsert_ai_cache(
            conn,
            url_hash=url_hash,
            url=url,
            fingerprint=fingerprint,
            video_title=video_title,
            subtitle_text=subtitle_text,
            source=subtitle_source,
            result_json=result_json,
            part_info=part_info,
            platform=platform,
            prompt_version=prompt_version,
            now=now,
        )
        _cleanup_old_cache(conn)
        _upsert_history(
            conn,
            user_id=user_id,
            guest_id=guest_id,
            url_hash=url_hash,
            url=url,
            title=video_title,
            platform=platform,
        )
        _insert_usage(
            conn,
            user_id=user_id,
            guest_id=guest_id,
            action="summary",
        )

    return result_json


def commit_subtitle_generation(
    *,
    url: str,
    info,
    fingerprint: str | None,
    subtitle_text: str,
    subtitle_source: str,
    subtitle_language: str,
    part_info: str,
    platform: str,
    whisper_raw_text: str,
) -> None:
    """Atomically replace video metadata and a completed subtitle transcript."""
    subtitle_text = _require_text(subtitle_text, "subtitle")
    info_dict, info_json = _normalize_info(info)
    now = _cache_timestamp()
    url_hash = _url_hash(url)

    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _upsert_video_info(
            conn,
            url_hash=url_hash,
            url=url,
            fingerprint=fingerprint,
            info=info_dict,
            info_json=info_json,
            now=now,
        )
        _replace_video_subtitle(
            conn,
            url=url,
            info=info_dict,
            platform=platform,
            part_info=part_info,
            subtitle_text=subtitle_text,
            subtitle_source=subtitle_source,
            subtitle_language=subtitle_language,
        )
        _upsert_whisper(
            conn,
            url_hash=url_hash,
            url=url,
            fingerprint=fingerprint,
            subtitle_text=subtitle_text,
            language=subtitle_language,
            raw_text=str(whisper_raw_text or ""),
            now=now,
        )


def commit_cached_generation(
    *,
    url: str,
    video_title: str,
    subtitle_text: str,
    source: str,
    result: dict,
    required_value,
    artifact_name: str,
    fingerprint: str | None,
    part_info: str,
    platform: str,
    prompt_version: int,
    user_id: int | None,
    guest_id: str | None,
    usage_action: str | None = None,
) -> str:
    """Atomically replace a cached AI artifact after validating its output."""
    _require_artifact(required_value, artifact_name)
    result_json = _encode_json(result, "generation result")
    now = _cache_timestamp()
    url_hash = _url_hash(url)

    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _upsert_ai_cache(
            conn,
            url_hash=url_hash,
            url=url,
            fingerprint=fingerprint,
            video_title=video_title,
            subtitle_text=subtitle_text,
            source=source,
            result_json=result_json,
            part_info=part_info,
            platform=platform,
            prompt_version=prompt_version,
            now=now,
        )
        _cleanup_old_cache(conn)
        _upsert_history(
            conn,
            user_id=user_id,
            guest_id=guest_id,
            url_hash=url_hash,
            url=url,
            title=video_title,
            platform=platform,
        )
        if usage_action:
            _insert_usage(
                conn,
                user_id=user_id,
                guest_id=guest_id,
                action=usage_action,
            )

    return result_json


def _validate_full_payload(result: Any) -> dict:
    if not isinstance(result, dict):
        raise InvalidGenerationResult("generation result must be an object")
    validate_summary_result(result.get("result"))
    return result


def _require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidGenerationResult(f"{name} result is empty")
    return value


def _require_artifact(value: Any, name: str) -> None:
    if isinstance(value, str):
        valid = bool(value.strip())
    elif isinstance(value, (list, tuple, dict, set)):
        valid = bool(value)
    else:
        valid = value is not None
    if not valid:
        raise InvalidGenerationResult(f"{name} result is empty")


def _encode_json(value: Any, name: str) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise InvalidGenerationResult(f"{name} is not JSON serializable") from exc


def _cache_timestamp() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def _normalize_info(info) -> tuple[dict, str]:
    if hasattr(info, "model_dump"):
        info_dict = info.model_dump()
    elif isinstance(info, dict):
        info_dict = dict(info)
    else:
        try:
            info_dict = dict(info)
        except (TypeError, ValueError) as exc:
            raise InvalidGenerationResult("video metadata is invalid") from exc
    return info_dict, _encode_json(info_dict, "video metadata")


def _upsert_video_info(
    conn,
    *,
    url_hash: str,
    url: str,
    fingerprint: str | None,
    info: dict,
    info_json: str,
    now: str,
) -> None:
    conn.execute(
        """
        INSERT INTO video_info_cache (
            url_hash, url, fingerprint, duration, title, info_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url_hash) DO UPDATE SET
            url = excluded.url,
            fingerprint = excluded.fingerprint,
            duration = excluded.duration,
            title = excluded.title,
            info_json = excluded.info_json,
            created_at = excluded.created_at
        """,
        (
            url_hash,
            url,
            fingerprint or "",
            info.get("duration") or 0,
            str(info.get("title") or ""),
            info_json,
            now,
        ),
    )


def _replace_video_subtitle(
    conn,
    *,
    url: str,
    info: dict,
    platform: str,
    part_info: str,
    subtitle_text: str,
    subtitle_source: str,
    subtitle_language: str,
) -> None:
    video = conn.execute("SELECT id FROM videos WHERE url = ?", (url,)).fetchone()
    values = (
        str(info.get("title") or ""),
        platform or str(info.get("extractor") or ""),
        info.get("uploader"),
        info.get("duration"),
        info.get("thumbnail"),
        info.get("description"),
        part_info or "",
    )
    if video:
        video_id = video["id"]
        conn.execute(
            """
            UPDATE videos
            SET title = COALESCE(NULLIF(?, ''), title),
                platform = COALESCE(NULLIF(?, ''), platform),
                uploader = COALESCE(NULLIF(?, ''), uploader),
                duration = COALESCE(?, duration),
                thumbnail_url = COALESCE(NULLIF(?, ''), thumbnail_url),
                description = COALESCE(NULLIF(?, ''), description),
                part_info = COALESCE(NULLIF(?, ''), part_info),
                status = 'done',
                error_message = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (*values, video_id),
        )
    else:
        cursor = conn.execute(
            """
            INSERT INTO videos (
                url, title, platform, uploader, duration, thumbnail_url,
                description, part_info, status, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'done', NULL)
            """,
            (url, *values),
        )
        video_id = cursor.lastrowid

    conn.execute("DELETE FROM subtitles WHERE video_id = ?", (video_id,))
    conn.execute(
        """
        INSERT INTO subtitles (
            video_id, source, language, full_text, segments_json
        ) VALUES (?, ?, ?, ?, NULL)
        """,
        (video_id, subtitle_source, subtitle_language, subtitle_text),
    )


def _upsert_whisper(
    conn,
    *,
    url_hash: str,
    url: str,
    fingerprint: str | None,
    subtitle_text: str,
    language: str,
    raw_text: str,
    now: str,
) -> None:
    conn.execute(
        """
        INSERT INTO whisper_cache (
            url_hash, url, fingerprint, subtitle_text, language, raw_text, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url_hash) DO UPDATE SET
            url = excluded.url,
            fingerprint = excluded.fingerprint,
            subtitle_text = excluded.subtitle_text,
            language = excluded.language,
            raw_text = excluded.raw_text,
            created_at = excluded.created_at
        """,
        (
            url_hash,
            url,
            fingerprint or "",
            subtitle_text,
            language,
            raw_text,
            now,
        ),
    )


def _upsert_ai_cache(
    conn,
    *,
    url_hash: str,
    url: str,
    fingerprint: str | None,
    video_title: str,
    subtitle_text: str,
    source: str,
    result_json: str,
    part_info: str,
    platform: str,
    prompt_version: int,
    now: str,
) -> None:
    conn.execute(
        """
        INSERT INTO ai_cache (
            url_hash, url, fingerprint, video_title, subtitle_text, source,
            result_json, part_info, platform, notes_chars, prompt_version,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url_hash) DO UPDATE SET
            url = excluded.url,
            fingerprint = excluded.fingerprint,
            video_title = excluded.video_title,
            subtitle_text = excluded.subtitle_text,
            source = excluded.source,
            result_json = excluded.result_json,
            part_info = excluded.part_info,
            platform = excluded.platform,
            notes_chars = excluded.notes_chars,
            prompt_version = excluded.prompt_version,
            updated_at = excluded.updated_at
        """,
        (
            url_hash,
            url,
            fingerprint or "",
            video_title,
            subtitle_text,
            source,
            result_json,
            part_info or "",
            platform or "",
            _compute_notes_chars(result_json),
            int(prompt_version or 0),
            now,
            now,
        ),
    )


def _upsert_history(
    conn,
    *,
    user_id: int | None,
    guest_id: str | None,
    url_hash: str,
    url: str,
    title: str,
    platform: str,
) -> None:
    if user_id is not None:
        owner_column = "user_id"
        owner_value = user_id
    elif guest_id:
        owner_column = "guest_id"
        owner_value = guest_id
    else:
        return
    conn.execute(
        f"""
        INSERT OR IGNORE INTO user_history (
            {owner_column}, url_hash, url, video_title, platform, status
        ) VALUES (?, ?, ?, ?, ?, 'done')
        """,
        (owner_value, url_hash, url, title, platform),
    )
    conn.execute(
        f"""
        UPDATE user_history
        SET url = ?, video_title = ?, platform = ?, status = 'done'
        WHERE {owner_column} = ? AND url_hash = ?
        """,
        (url, title, platform, owner_value, url_hash),
    )


def _insert_usage(
    conn,
    *,
    user_id: int | None,
    guest_id: str | None,
    action: str,
) -> None:
    if user_id is None and not guest_id:
        return
    conn.execute(
        """
        INSERT INTO usage_logs (user_id, guest_id, action, status)
        VALUES (?, ?, ?, 'SUCCESS')
        """,
        (user_id, guest_id, action),
    )
