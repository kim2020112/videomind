"""Durable, independently generated learning artifacts and quota reservations."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time

import config
from database import get_db, get_subtitle_from_db, save_subtitle_to_db
from core import job_store, job_signals
from core.logging_config import get_logger
from core.subtitle_validation import validate_cached_subtitle, SubtitleIdentityError
from core.cache import _get_cached_raw, _url_hash, get_video_info_cache, save_video_info_cache, video_fingerprint, _cleanup_old_cache
from core.generation_commit import (
    _upsert_ai_cache, _upsert_history, _cache_timestamp, validate_summary_result,
)
from core.job_scheduler import JobCancelled
from core.models import VideoInfo
from core.pipeline.subtitle import fetch_subtitle, _build_part_info
from core.pipeline.summary import run_summary
from core.pipeline.mindmap import run_mindmap
from core.pipeline.notes import run_notes
from core.pipeline.qanda import run_qanda
from core.features import is_whisper_available
from core.video import canonical_video_url, video_duration_for_url
from core.whisper import estimate_transcribe_time
from core.content_state import register_content_functions, decode_payload, content_state, present_modules

TARGETS = ("summary", "mindmap", "notes", "qa")
KEYS = {"summary": "result", "mindmap": "mindmap_markdown", "notes": "notes", "qa": "qa_pairs"}
LABELS = {"summary": "摘要", "mindmap": "导图", "notes": "笔记", "qa": "精选问答"}
logger = get_logger(__name__)


def revision(text):
    return hashlib.sha256((text or "").strip().encode()).hexdigest()


def prompt_version(target):
    return getattr(config, {"summary": "SUMMARY", "mindmap": "MINDMAP", "notes": "NOTES", "qa": "QANDA"}[target] + "_PROMPT_VERSION")


def payload_for(url):
    cached = _get_cached_raw(url)
    return decode_payload(cached["result_json"] if cached else None)


def artifact_states(payload, text):
    states = {}
    existing = present_modules(payload)
    for target in TARGETS:
        content = payload.get(KEYS[target])
        exists = target in existing
        metadata = payload.get("_artifacts")
        meta = metadata.get(target) if isinstance(metadata, dict) else None
        meta = meta if isinstance(meta, dict) else {}
        stale = bool(meta and (meta.get("subtitle_revision") != revision(text)
                              or meta.get("prompt_version") != prompt_version(target)))
        states[target] = {"status": "done" if exists else "missing", "stale": stale,
                          "version_unknown": bool(exists and not meta), **meta}
    return states


def complete_payload(payload):
    return len(present_modules(payload)) == len(TARGETS)


def content_coverage(payload, has_subtitle=False):
    return content_state(payload, has_subtitle)["coverage"]


def release_usage(operation_id):
    with get_db() as conn:
        conn.execute("DELETE FROM learning_usage WHERE operation_id = ? AND status = 'reserved'", (operation_id,))


def recover_usage_reservations():
    """Release abandoned streams/terminal tasks at startup, retaining resumable jobs."""
    with get_db() as conn:
        conn.execute(
            "DELETE FROM learning_usage WHERE status = 'reserved' AND NOT EXISTS ("
            "SELECT 1 FROM background_jobs j WHERE j.id = learning_usage.operation_id "
            "AND j.status IN ('queued','downloading','transcribing','generating','awaiting_confirmation'))"
        )


def reserve_usage(job):
    """Serialize admission against successful calls and all pending reservations."""
    from core.auth import USER_DAILY_LIMIT, GUEST_DAILY_LIMIT
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT status FROM learning_usage WHERE operation_id = ?", (job["task_id"],)).fetchone()
        if existing:
            return
        if job.get("user_id") is not None:
            user = conn.execute("SELECT role, daily_limit FROM users WHERE id = ?", (job["user_id"],)).fetchone()
            if not user:
                raise ValueError("登录身份已失效")
            limit = 999999 if user["role"] == "admin" else user["daily_limit"] or USER_DAILY_LIMIT
            field, owner = "user_id", job["user_id"]
        else:
            field, owner, limit = "guest_id", job.get("guest_id"), GUEST_DAILY_LIMIT
        used = conn.execute(
            f"SELECT COUNT(*) FROM usage_logs WHERE {field} = ? AND status = 'SUCCESS' AND created_at >= date('now')",
            (owner,),
        ).fetchone()[0]
        reserved = conn.execute(
            f"SELECT COUNT(*) FROM learning_usage WHERE {field} = ? AND status = 'reserved'",
            (owner,),
        ).fetchone()[0]
        if used + reserved >= limit:
            raise ValueError(f"今日 AI 次数已用完或已预占（{used}/{limit}）")
        conn.execute("INSERT INTO learning_usage(operation_id, user_id, guest_id) VALUES (?, ?, ?)",
                     (job["task_id"], job.get("user_id"), job.get("guest_id")))


def charge_usage(job, action="qa"):
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        changed = conn.execute("UPDATE learning_usage SET status = 'charged' WHERE operation_id = ? AND status = 'reserved'", (job["task_id"],)).rowcount
        if changed:
            conn.execute("INSERT INTO usage_logs(user_id, guest_id, action, status) VALUES (?, ?, ?, 'SUCCESS')",
                         (job.get("user_id"), job.get("guest_id"), action))


def emit(task_id, event_type, data):
    with get_db() as conn:
        conn.execute("INSERT INTO learning_events(task_id, event_json) VALUES (?, ?)",
                     (task_id, json.dumps({"type": event_type, "data": data}, ensure_ascii=False)))
    job_signals.notify(task_id)


def events_after(task_id, after=0):
    with get_db() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT id, event_json FROM learning_events WHERE task_id = ? AND id > ? ORDER BY id LIMIT 200",
            (task_id, after),
        ).fetchall()]


def check_cancel(job):
    if job_store.is_cancel_requested(job["task_id"]):
        raise JobCancelled()


def save_artifact(job, info, text, source, language, target, content, input_source="subtitle"):
    """Merge one complete artifact and bill the operation exactly once in one transaction."""
    url = job["url"]
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT cancel_requested, result_json FROM background_jobs WHERE id = ?", (job["task_id"],)).fetchone()
        if current["cancel_requested"]:
            raise JobCancelled()
        if input_source == "subtitle":
            sub = conn.execute("SELECT s.full_text FROM subtitles s JOIN videos v ON v.id = s.video_id WHERE v.url = ?", (url,)).fetchone()
            if sub and revision(sub[0]) != revision(text):
                raise ValueError("字幕已变化，本次结果未替换旧资料，请重新生成")
        row = conn.execute("SELECT result_json, subtitle_text, source FROM ai_cache WHERE url_hash = ?", (_url_hash(url),)).fetchone()
        payload = decode_payload(row[0] if row else None)
        meta = {"subtitle_revision": revision(text), "prompt_version": prompt_version(target),
                "generated_at": _cache_timestamp(), "input_source": input_source}
        from core.ai_config import get_effective_model
        # Model configuration can change independently of an operation.
        try:
            meta["model"] = get_effective_model()
        except Exception:
            meta["model"] = ""
        if input_source == "description":
            payload["description_summary"] = content
            payload["description_summary_meta"] = meta
        else:
            payload[KEYS[target]] = content
            if not isinstance(payload.get("_artifacts"), dict):
                payload["_artifacts"] = {}
            payload["_artifacts"][target] = meta
        fingerprint = video_fingerprint(info.extractor, info.id) if info.extractor and info.id else None
        _upsert_ai_cache(conn, url_hash=_url_hash(url), url=url, fingerprint=fingerprint,
                         video_title=info.title, subtitle_text=text if input_source == "subtitle" else row["subtitle_text"] if row else "",
                         source=source if input_source == "subtitle" else row["source"] if row else "description", result_json=json.dumps(payload, ensure_ascii=False),
                         part_info=_build_part_info(url, info), platform=info.extractor or "",
                         prompt_version=max(prompt_version(t) for t in TARGETS), now=_cache_timestamp())
        _upsert_history(conn, user_id=job.get("user_id"), guest_id=job.get("guest_id"),
                        url_hash=_url_hash(url), url=url, title=info.title, platform=info.extractor or "")
        usage = conn.execute("SELECT status FROM learning_usage WHERE operation_id = ?", (job["task_id"],)).fetchone()
        if not usage:
            raise ValueError("生成额度预占已失效，请重新提交")
        if usage[0] == "reserved":
            conn.execute("INSERT INTO usage_logs(user_id, guest_id, action, status) VALUES (?, ?, 'learning', 'SUCCESS')",
                         (job.get("user_id"), job.get("guest_id")))
            conn.execute("UPDATE learning_usage SET status = 'charged' WHERE operation_id = ?", (job["task_id"],))
        state = json.loads(current["result_json"] or "{}")
        state.setdefault("modules", {})[target] = {"status": "done", "new": True}
        conn.execute("UPDATE background_jobs SET result_json = ? WHERE id = ?",
                     (json.dumps(state, ensure_ascii=False), job["task_id"]))
        _cleanup_old_cache(conn)
    emit(job["task_id"], "artifact_saved", {"target": target, "content": content, "input_source": input_source})


def _generate(job, info, text, source, language, target):
    check_cancel(job)
    task_id = job["task_id"]
    if job["payload"].get("input_source") == "description":
        from core.summarizer import summarize_from_description
        result = summarize_from_description(info.title, info.description)
        validate_summary_result(result)
        save_artifact(job, info, info.description, "description", language, target, result, "description")
        return
    if target == "mindmap":
        content = run_mindmap(text, info.title, task_id)
    else:
        iterator = {"summary": lambda: run_summary(text, info.title, task_id),
                    "notes": lambda: run_notes(text, info.title, job["url"], task_id),
                    "qa": lambda: run_qanda(text, info.title, task_id)}[target]()
        content = "" if target == "notes" else None
        for event in iterator:
            check_cancel(job)
            emit(task_id, "module_event", {"target": target, "type": event.type, "data": event.data})
            if event.type in {"error", "warn"}:
                raise ValueError(event.data.get("message", "生成失败"))
            if target == "summary" and event.type == "result" and not event.data.get("is_partial"):
                content = event.data
            elif target == "notes" and event.type == "notes_text":
                content += event.data.get("text", "")
            elif target == "qa" and event.type == "qa_pairs":
                content = event.data
    if target == "summary":
        validate_summary_result(content)
    elif not content or (isinstance(content, str) and not content.strip()):
        raise ValueError("未生成完整有效的内容")
    elif target == "qa" and (not isinstance(content, list) or any(not p.get("question") or not p.get("answer") for p in content)):
        raise ValueError("问答内容不完整")
    save_artifact(job, info, text, source, language, target, content)


def _set_module(job, target, state):
    current = job_store.get_job(job["task_id"])
    result = current.get("result") or {}
    result.setdefault("modules", {})[target] = state
    job_store.update_job(job["task_id"], result=result)
    emit(job["task_id"], "module_status", {"target": target, **state})


async def run_learning_job(job, scheduler):
    from api.routes import downloader
    from core.video_metadata import learning_video_info
    from core.auth import add_user_history
    task_id = job["task_id"]
    payload = job.get("payload") or {}
    targets = payload.get("targets", [])
    info_data = get_video_info_cache(job["url"]) or payload.get("info")
    info = VideoInfo.model_validate(info_data) if info_data else await asyncio.to_thread(learning_video_info, job["url"], downloader)
    url = canonical_video_url(job["url"], info)
    info.webpage_url = url
    job["url"] = url
    job_store.update_job(task_id, url=url, url_hash=_url_hash(url))
    save_video_info_cache(url, info)
    check_cancel(job)
    text, source, language = "", "", job.get("lang", "")
    if payload.get("input_source") == "description":
        if not info.description or len(info.description.strip()) < 20:
            raise ValueError("该视频没有足够的简介内容")
    else:
        job_store.update_job(task_id, message="正在获取字幕")
        subtitle_started = time.monotonic()
        cached = get_subtitle_from_db(url)
        if not cached:
            legacy = _get_cached_raw(url)
            if legacy and legacy.get("subtitle_text") and legacy.get("source") != "description":
                cached = {"full_text": legacy["subtitle_text"], "source": legacy["source"], "language": ""}
                save_subtitle_to_db(url, cached["source"], "", cached["full_text"], info.title, info.extractor or "", _build_part_info(url, info))
        if cached:
            try:
                cached = validate_cached_subtitle(url, cached, info)
            except SubtitleIdentityError:
                cached = None
        refresh = payload.get("refresh_subtitle", False)
        if cached and not refresh:
            text, source, language = cached["full_text"], cached["source"], cached["language"]
        else:
            # Platform SDKs contain blocking HTTP calls; keep the API event loop responsive.
            text, source, language = await asyncio.to_thread(
                lambda: asyncio.run(fetch_subtitle(url, info, job.get("lang"), trace_id=task_id, refresh=refresh, persist=True)))
        check_cancel(job)
        if not text:
            duration = video_duration_for_url(url, info)
            if not is_whisper_available() or (config.WHISPER_MAX_DURATION > 0 and duration > config.WHISPER_MAX_DURATION):
                state = job_store.get_job(task_id).get("result") or {}
                job_store.update_job(task_id, result={**state, "subtitle_unavailable": True})
                raise ValueError("没有平台字幕，语音转录不可用或视频超过转录时长限制；可仅根据简介生成摘要")
            if not payload.get("allow_transcription"):
                release_usage(task_id)
                job_store.update_job(task_id, status="awaiting_confirmation", message="未找到平台字幕，请确认是否开始语音转录",
                                     estimated_seconds=estimate_transcribe_time(duration), payload={**payload, "info": info.model_dump()})
                emit(task_id, "awaiting_confirmation", {})
                return
            result_path = scheduler.work_dir / f"{task_id}-subtitle.json"
            job["payload"]["info"] = info.model_dump()
            try:
                worker = await scheduler.run_worker_subprocess(task_id, scheduler.command_factory(job, result_path))
            finally:
                result_path.unlink(missing_ok=True)
            check_cancel(job)
            text, source, language = worker.get("subtitle_text", ""), "whisper", worker.get("language", "auto")
            if len(text.strip()) < 20:
                raise ValueError("语音转录结果为空或过短")
            save_subtitle_to_db(url, source, language, text, info.title, info.extractor or "", _build_part_info(url, info), worker.get("segments"))
        elif not cached or refresh:
            # Native fetch persists precise segments; do not replace them with text-only rows.
            stored = get_subtitle_from_db(url)
            if not stored or stored["full_text"] != text:
                save_subtitle_to_db(url, source, language, text, info.title, info.extractor or "", _build_part_info(url, info))
        add_user_history(user_id=job.get("user_id"), guest_id=job.get("guest_id"), url_hash=_url_hash(url),
                         url=url, title=info.title, platform=info.extractor or "")
        emit(task_id, "subtitle_ready", {})
        logger.info("subtitle_ready task_id=%s source=%s cache_hit=%s elapsed_ms=%.1f",
                    task_id, source, bool(cached and not refresh),
                    (time.monotonic() - subtitle_started) * 1000)
    check_cancel(job)
    snapshot = payload_for(url)
    states = artifact_states(snapshot, text)
    pending = []
    completed = (job_store.get_job(task_id).get("result") or {}).get("modules", {})
    for target in targets:
        description_hit = payload.get("input_source") == "description" and bool(snapshot.get("description_summary"))
        reusable = description_hit or (states[target]["status"] == "done" and not states[target]["stale"])
        if completed.get(target, {}).get("new") or (reusable and not payload.get("force")):
            if not completed.get(target, {}).get("new"):
                _set_module(job, target, {"status": "done", "reused": True})
        else:
            pending.append(target)
            _set_module(job, target, {"status": "queued"})
    if pending:
        if payload.get("input_source", "subtitle") == "subtitle":
            from core.ai_client import effective_speech_chars
            if effective_speech_chars(text) < 20:
                raise ValueError("字幕缺乏有效语音内容，无法生成学习资料")
        reserve_usage(job)
    for index, target in enumerate(pending):
        check_cancel(job)
        job_store.update_job(task_id, status="generating", message=f"正在生成{LABELS[target]}", progress=40 + 55 * index / len(pending))
        _set_module(job, target, {"status": "generating"})
        try:
            await asyncio.to_thread(_generate, job, info, text, source, language, target)
        except JobCancelled:
            raise
        except Exception as exc:
            _set_module(job, target, {"status": "failed", "error": str(exc)})
    check_cancel(job)
    modules = (job_store.get_job(task_id).get("result") or {}).get("modules", {})
    failed = [t for t in targets if modules.get(t, {}).get("status") == "failed"]
    successes = [t for t in targets if modules.get(t, {}).get("status") == "done"]
    status = "partial" if failed and successes else "failed" if failed else "done"
    job_store.update_job(task_id, status=status, progress=100, message="部分资料生成失败，可单独重试" if failed else "处理完成",
                         error="；".join(f"{LABELS[t]}：{modules[t]['error']}" for t in failed) or None)
    release_usage(task_id)
    emit(task_id, "finished", {"status": status})


def workspace(url, identity):
    sub = get_subtitle_from_db(url)
    cached = _get_cached_raw(url)
    if not sub and cached and cached.get("subtitle_text") and cached.get("source") != "description":
        sub = {"full_text": cached["subtitle_text"], "source": cached["source"], "language": "", "segments": []}
    subtitle_warning = ''
    try:
        sub = validate_cached_subtitle(url, sub, get_video_info_cache(url))
    except SubtitleIdentityError as exc:
        sub = None
        subtitle_warning = str(exc)
    result = payload_for(url)
    task = job_store.find_active_job(_url_hash(url), user_id=identity.get("user_id"), guest_id=identity.get("guest_id"))
    if not task:
        owner_sql, params = job_store._owner_clause(identity.get("user_id"), identity.get("guest_id"))
        with get_db() as conn:
            row = conn.execute(f"SELECT id FROM background_jobs WHERE {owner_sql} AND url_hash = ? AND job_type = 'learning' ORDER BY created_at DESC LIMIT 1",
                               [*params, _url_hash(url)]).fetchone()
        task = job_store.get_job(row[0], user_id=identity.get("user_id"), guest_id=identity.get("guest_id")) if row else None
    # Old prompt versions stay readable. The metadata records only what is known.
    states = artifact_states(result, sub["full_text"] if sub else "")
    if subtitle_warning:
        for state in states.values():
            if state["status"] == "done":
                state["stale"] = True
    cleared = subtitle_is_cleared(url, identity)
    if cleared:
        sub = None
    return {"url": url, "subtitle": {**sub, "text": sub["full_text"], "revision": revision(sub["full_text"])} if sub else None,
            "artifacts": result, "modules": states, "task": task,
            "coverage": content_coverage(result, bool(sub)), "subtitle_cleared": cleared, "subtitle_warning": subtitle_warning}


def record_visit(url, identity):
    """Associate existing content with this identity; never change a job or a favorite."""
    sub = get_subtitle_from_db(url)
    cached = _get_cached_raw(url)
    has_subtitle = bool(sub and sub["full_text"].strip()) or bool(cached and cached.get("source") != "description" and (cached.get("subtitle_text") or "").strip())
    has_subtitle = has_subtitle and not subtitle_is_cleared(url, identity)
    state = content_state(cached.get("result_json") if cached else None, has_subtitle)
    if not (has_subtitle or state["module_count"] or state["has_description_summary"]):
        return {"recorded": False, "content": state}
    info = get_video_info_cache(url) or {}
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO user_history(user_id,guest_id,url_hash,url,video_title,platform,status) "
            "VALUES (?,?,?,?,?,?,'done')",
            (identity.get("user_id"), identity.get("guest_id"), _url_hash(url), url,
             info.get("title") or (cached or {}).get("video_title", ""),
             info.get("extractor") or (cached or {}).get("platform", "")),
        )
    return {"recorded": True, "content": state}


def _subtitle_owner_scope(conn, url, identity):
    from core.cache import _extract_video_key, _extract_part_index
    register_content_functions(conn)
    owner, params = job_store._owner_clause(identity.get("user_id"), identity.get("guest_id"))
    return (f"{owner} AND vm_video_key(url) = ? AND vm_part_index(url) = ?",
            [*params, _extract_video_key(url), _extract_part_index(url)])


def subtitle_is_cleared(url, identity):
    with get_db() as conn:
        where, params = _subtitle_owner_scope(conn, url, identity)
        return bool(conn.execute(f"SELECT 1 FROM user_history WHERE {where} AND subtitle_cleared = 1 LIMIT 1", params).fetchone())


def restore_subtitle(url, identity):
    """Explicit acquisition makes the existing shared transcript visible again."""
    with get_db() as conn:
        where, params = _subtitle_owner_scope(conn, url, identity)
        conn.execute(f"UPDATE user_history SET subtitle_cleared=0 WHERE {where}", params)


def clear_subtitle(url, identity):
    """Remove this identity's transcript association, preserving shared content."""
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        owner, owner_params = job_store._owner_clause(identity.get("user_id"), identity.get("guest_id"))
        register_content_functions(conn)
        from core.cache import _extract_video_key, _extract_part_index
        active = conn.execute(
            f"SELECT 1 FROM background_jobs WHERE {owner} AND vm_video_key(url)=? AND vm_part_index(url)=? "
            "AND status IN ('queued','downloading','transcribing','generating','awaiting_confirmation') LIMIT 1",
            [*owner_params, _extract_video_key(url), _extract_part_index(url)],
        ).fetchone()
        if active:
            raise ValueError("当前视频任务尚未结束，请完成或取消后再清空字幕")
        conn.execute(
            "INSERT OR IGNORE INTO user_history(user_id,guest_id,url_hash,url,status,subtitle_cleared) VALUES (?,?,?,?,'done',1)",
            (identity.get("user_id"), identity.get("guest_id"), _url_hash(url), url),
        )
        where, params = _subtitle_owner_scope(conn, url, identity)
        conn.execute(f"UPDATE user_history SET subtitle_cleared=1 WHERE {where}", params)
    return workspace(url, identity)
