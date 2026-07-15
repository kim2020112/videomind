"""SSE 流式端点 — /api/summarize/stream + /api/chat/stream。

所有 SSE 端点返回 text/event-stream，事件格式: data: {"type":"...","data":{...}}\n\n
"""

import asyncio
import json
import re
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from core.pipeline import PipelineEvent
from core.pipeline.subtitle import (
    BilibiliSubtitleUnavailable,
    fetch_subtitle,
    _build_part_info,
    extract_bvid,
)
from core.pipeline.subtitle_postprocess import correct_subtitle_text
from core.pipeline.summary import run_summary
from core.pipeline.mindmap import run_mindmap
from core.pipeline.notes import run_notes
from core.pipeline.qanda import run_qanda
from core.pipeline.tags import run_tags
from core.logging_config import get_logger

logger = get_logger(__name__)

from core.summary_models import SummarizeRequest, ChatRequest, QaGenerationRequest
from core.summarizer import summarize_from_description
from core.ai_client import stream_chat
from config import WHISPER_MAX_DURATION
from core.cache import (
    get_cached,
    get_video_info_cache, video_fingerprint,
    _get_cached_raw, get_whisper_cache,
)
from core.generation_commit import (
    InvalidGenerationResult,
    commit_cached_generation,
    commit_full_generation,
    validate_summary_result,
)
from core.whisper import estimate_transcribe_time
from core.video import canonical_video_url, is_bilibili_video, video_duration_for_url
from core.background_pipeline import enqueue_whisper_job
from core.job_store import find_active_job
from core.tag_extractor import detect_platform
from core.features import is_ai_available, is_whisper_available

from api.routes import extract_url, downloader
from api.security import ensure_public_http_url, require_identity
from core.auth import check_usage_limit, log_usage, add_user_history
from core.cache import _url_hash

router = APIRouter()


# ──── SSE 工具 ────

def _to_sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


async def _sse_generator(sync_gen):
    """将同步 PipelineEvent generator 转为 SSE 字节流。"""
    loop = asyncio.get_event_loop()
    queue = asyncio.Queue()

    def _run():
        try:
            for event in sync_gen:
                if isinstance(event, PipelineEvent):
                    payload = {"type": event.type, "data": event.data}
                else:
                    # 兼容旧 tuple 格式
                    payload = {"type": event[0], "data": event[1]}
                loop.call_soon_threadsafe(queue.put_nowait, payload)
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "data": {"message": str(e)}})
        loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(None, _run)

    while True:
        payload = await queue.get()
        if payload is None:
            break
        yield _to_sse(payload)


def _sse_headers():
    return {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}


# ──── 缓存重放 ────

def _replay_cached(cached: dict, identity: dict, url: str, trace_id: str):
    """从缓存重放 SSE 事件流。"""
    result_data = json.loads(cached["result_json"])

    # 确保 videos 表有记录
    from database import get_subtitle_from_db as _get_sub, save_subtitle_to_db as _save_sub, get_db as _get_db
    if not _get_sub(url):
        _save_sub(url, cached.get("source", ""), "", cached.get("subtitle_text", ""),
                  cached.get("video_title", ""), part_info=cached.get("part_info", ""))
    else:
        with _get_db() as _conn:
            _vid = _conn.execute("SELECT id FROM videos WHERE url = ?", (url,)).fetchone()
            if _vid:
                _updates, _params = [], []
                if cached.get("video_title"):
                    _updates.append("title = ?")
                    _params.append(cached["video_title"])
                if cached.get("platform"):
                    _updates.append("platform = ?")
                    _params.append(cached["platform"])
                if cached.get("part_info"):
                    _updates.append("part_info = ?")
                    _params.append(cached["part_info"])
                if _updates:
                    _params.append(_vid["id"])
                    _conn.execute(f"UPDATE videos SET {', '.join(_updates)} WHERE id = ?", _params)

    add_user_history(
        user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
        url_hash=_url_hash(url), url=url,
        title=cached.get("video_title", ""), platform=cached.get("platform", ""),
    )
    log_usage(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
              action="summary", status="CACHE_HIT")

    def _gen():
        yield PipelineEvent("progress", {"stage": "cache_hit", "message": "已有学习记录，直接加载"})
        result = result_data.get("result", {})
        if result:
            yield PipelineEvent("result", result)
        if result_data.get("mindmap_markdown"):
            yield PipelineEvent("mindmap", {"markdown": result_data["mindmap_markdown"]})
        if result_data.get("notes"):
            yield PipelineEvent("notes", {"markdown": result_data["notes"]})
        if result_data.get("flashcards"):
            yield PipelineEvent("flashcards", result_data["flashcards"])
        yield PipelineEvent("done", {})

    return StreamingResponse(_sse_generator(_gen()), media_type="text/event-stream", headers=_sse_headers())


# ──── 主端点 ────

@router.post("/api/summarize/stream")
async def summarize_stream(req: SummarizeRequest, request: Request):
    """SSE 流式 AI 视频总结。"""
    if not is_ai_available():
        raise HTTPException(status_code=503, detail="feature_unavailable: AI 功能不可用（SDK 未安装、未启用或未配置 API Key）")
    try:
        trace_id = uuid.uuid4().hex[:8]
        url = extract_url(req.url)
        ensure_public_http_url(url)
        identity = require_identity(request)

        # ── 缓存检查 ──
        cached = get_cached(url)
        if req.force:
            if not cached and req.mode != "full":
                # prompt_version 不匹配导致 get_cached 返回 None，用 _get_cached_raw 兜底
                from core.cache import _get_cached_raw
                cached = _get_cached_raw(url)
                if not cached:
                    raise HTTPException(status_code=400, detail="尚无缓存，请先生成完整 AI 总结")

        # 缓存命中 + 全量模式 → 重放
        if cached and cached.get("result_json") and req.mode == "full" and not req.force:
            return _replay_cached(cached, identity, url, trace_id)

        # ── AI 使用次数检查 ──
        allowed, used, limit = check_usage_limit(
            identity.get("user_id"), identity.get("guest_id"), identity.get("guest_sig")
        )
        if not allowed:
            raise HTTPException(status_code=429, detail=f"今日 AI 次数已用完（{used}/{limit}）")

        # ── 部分重新生成 ──
        if req.mode != "full":
            return await _handle_partial(req, cached, identity, url, trace_id)

        # ── 视频信息缓存预检（超长视频快速路径） ──
        cached_info = get_video_info_cache(url)
        cached_duration = video_duration_for_url(url, cached_info) if cached_info else 0
        if WHISPER_MAX_DURATION > 0 and cached_duration > WHISPER_MAX_DURATION:
            fast_resp = _try_long_video_fast_path(url, cached_info, identity)
            if fast_resp:
                return fast_resp

        # ── 快速后台转录判断（不调用 parse_info，立即返回） ──
        # 在 parse_info 之前判断，避免 10-30 秒的 yt-dlp 解析延迟
        # 用 URL 生成临时 url_hash（后续 parse_info 后会用 canonical_url 更新）
        fast_url_hash = _url_hash(url)

        # 检查是否已有活跃任务
        existing_job = find_active_job(
            fast_url_hash,
            user_id=identity.get("user_id"),
            guest_id=identity.get("guest_id"),
        )
        if existing_job:
            existing_task = existing_job["task_id"]
            dur = cached_duration
            def _already_running():
                yield PipelineEvent("background_started", {
                    "task_id": existing_task, "url_hash": fast_url_hash,
                    "estimated_seconds": 0, "duration": dur,
                    "message": "该视频已有转录任务在后台执行",
                })
                yield PipelineEvent("done", {})
            return StreamingResponse(_sse_generator(_already_running()), media_type="text/event-stream", headers=_sse_headers())

        # 快速判断是否应走后台：检查缓存中有无字幕 + 有无 Whisper 模型 + 时长
        fast_cached_sub = _quick_db_subtitle_check(url)
        cached_fp = cached_info.get("fingerprint") if cached_info else None
        if cached_fp:
            cached_whisper = get_whisper_cache(url, fingerprint=cached_fp)
            if cached_whisper and len(cached_whisper.strip()) >= 20:
                fast_cached_sub = True

        # B站视频：CC API 只需 BV ID，无需 parse_info，先尝试获取
        bilibili_lookup_unavailable = False
        if not fast_cached_sub:
            from core.pipeline.subtitle import try_get_bilibili_cc_subtitle
            cc_result = try_get_bilibili_cc_subtitle(url, cached_info)
            if cc_result and cc_result.get("has_subtitle"):
                fast_cached_sub = True
            elif is_bilibili_video(url, cached_info) and cc_result is None:
                bilibili_lookup_unavailable = True

        duration_from_cache = cached_duration
        need_whisper = (
            not fast_cached_sub
            and not bilibili_lookup_unavailable
            and is_whisper_available()
        )
        cached_audio_ready = (
            not is_bilibili_video(url, cached_info)
            or bool((cached_info or {}).get("audio_stream_url"))
        )

        if need_whisper and cached_info and cached_audio_ready:
            # 有缓存时长信息，立即走后台
            est = estimate_transcribe_time(duration_from_cache)
            job = enqueue_whisper_job(
                url_hash=fast_url_hash,
                url=url,
                identity=identity,
                lang=req.lang,
                estimated_seconds=est,
                info=cached_info,
                fingerprint=cached_fp,
            )
            task_id = job["task_id"]

            def _bg_start():
                yield PipelineEvent("background_started", {
                    "task_id": task_id, "url_hash": fast_url_hash,
                    "estimated_seconds": est, "duration": duration_from_cache,
                    "message": f"视频时长 {duration_from_cache // 60} 分 {duration_from_cache % 60} 秒，转录已加入后台队列",
                })
                yield PipelineEvent("done", {})
            return StreamingResponse(_sse_generator(_bg_start()), media_type="text/event-stream", headers=_sse_headers())

        # ── 解析视频信息（需要完整 info 的路径才走到这里） ──
        info = downloader.parse_info(url)
        fp = video_fingerprint(info.extractor, info.id) if info.extractor and info.id else None
        canonical_url = canonical_video_url(url, info)
        info.webpage_url = canonical_url

        # ── 二次缓存检查（指纹命中） ──
        if not cached and fp:
            cached = get_cached(canonical_url, fingerprint=fp)
            if cached and cached.get("result_json") and req.mode == "full" and not req.force:
                return _replay_cached(cached, identity, canonical_url, trace_id)

        url_hash = _url_hash(canonical_url)

        # 检查是否已有活跃任务（用 canonical_url 重新检查）
        if url_hash != fast_url_hash:
            existing_job = find_active_job(
                url_hash,
                user_id=identity.get("user_id"),
                guest_id=identity.get("guest_id"),
            )
            if existing_job:
                existing_task = existing_job["task_id"]
                def _already_running2():
                    yield PipelineEvent("background_started", {
                        "task_id": existing_task, "url_hash": url_hash,
                        "estimated_seconds": 0, "duration": info.duration or 0,
                        "message": "该视频已有转录任务在后台执行",
                    })
                    yield PipelineEvent("done", {})
                return StreamingResponse(_sse_generator(_already_running2()), media_type="text/event-stream", headers=_sse_headers())

        # 快速检查是否有非 Whisper 字幕源（需要完整 info 的网络检查）
        has_quick_sub = _quick_subtitle_check(canonical_url, info, req.lang, fp)
        if has_quick_sub is False and is_whisper_available():
            est = estimate_transcribe_time(info.duration or 0)
            job = enqueue_whisper_job(
                url_hash=url_hash,
                url=canonical_url,
                identity=identity,
                lang=req.lang,
                estimated_seconds=est,
                info=info,
                fingerprint=fp,
            )
            task_id = job["task_id"]

            def _bg_start():
                yield PipelineEvent("background_started", {
                    "task_id": task_id, "url_hash": url_hash,
                    "estimated_seconds": est, "duration": info.duration,
                    "message": f"视频时长 {info.duration // 60} 分 {info.duration % 60} 秒，转录已加入后台队列",
                })
                yield PipelineEvent("done", {})
            return StreamingResponse(_sse_generator(_bg_start()), media_type="text/event-stream", headers=_sse_headers())

        # ── 字幕获取 ──
        whisper_est = None
        if info.duration and info.duration > 120:
            whisper_est = estimate_transcribe_time(info.duration)

        subtitle_text, sub_source, sub_lang = await fetch_subtitle(
            canonical_url, info, req.lang, fingerprint=fp, trace_id=trace_id
        )

        # Whisper 字幕 AI 校正
        if sub_source == "whisper" and subtitle_text:
            subtitle_text = await correct_subtitle_text(
                subtitle_text, info.title, info.description or "", trace_id=trace_id
            )

        # ── 无字幕降级 ──
        if not subtitle_text:
            return _handle_no_subtitle(info, identity)

        # ── AI 流水线 ──
        def _gen():
            source_label = {
                "bilibili_cc": "B站CC字幕", "youtube_auto": "YouTube自动字幕",
                "ytdlp_native": "平台原生字幕", "whisper": "Whisper语音识别",
            }.get(sub_source, sub_source)

            # Whisper 转录完成，告知预估耗时（实际转录已在上方完成）
            if sub_source == "whisper" and whisper_est:
                yield PipelineEvent("whisper_estimate", {
                    "duration": info.duration, "estimated_seconds": whisper_est,
                    "message": f"Whisper 语音识别完成（视频 {info.duration // 60} 分 {info.duration % 60} 秒）",
                })

            yield PipelineEvent("progress", {
                "stage": "subtitle_loaded", "source": sub_source, "lang": sub_lang,
                "message": f"字幕就绪（{source_label}），开始 AI 分析...",
            })

            # 1. AI 摘要
            subtitle_for_rest = subtitle_text
            result_data = {}
            for event in run_summary(subtitle_text, info.title, trace_id):
                yield event
                if event.type == "result":
                    result_data = event.data
            validate_summary_result(result_data)

            # 2. 思维导图
            mindmap_md = run_mindmap(subtitle_for_rest, info.title, trace_id)
            if mindmap_md:
                yield PipelineEvent("mindmap", {"markdown": mindmap_md})

            # 3. 学习笔记
            notes_text = ""
            for event in run_notes(subtitle_for_rest, info.title, canonical_url, trace_id):
                yield event
                if event.type == "notes_text":
                    notes_text += event.data.get("text", "")

            # 4. 关键问答对
            qa_pairs_result = []
            for event in run_qanda(subtitle_for_rest, info.title, trace_id):
                yield event
                if event.type == "qa_pairs":
                    qa_pairs_result = event.data

            # ── 持久化 ──
            from core.cache import _max_prompt_version
            generated_result = {
                "result": result_data,
                "mindmap_markdown": mindmap_md,
                "notes": notes_text,
                "qa_pairs": qa_pairs_result,
            }
            platform_name = detect_platform(canonical_url, info.extractor or "")
            commit_full_generation(
                url=canonical_url,
                info=info,
                fingerprint=fp,
                subtitle_text=subtitle_text,
                subtitle_source=sub_source,
                subtitle_language=sub_lang,
                part_info=_build_part_info(canonical_url, info=info),
                platform=platform_name,
                result=generated_result,
                prompt_version=_max_prompt_version(),
                user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
            )

            # 标签提取
            summary_for_tags = result_data.get("summary", "")
            run_tags(canonical_url, info.title, summary_for_tags, trace_id)

            yield PipelineEvent("done", {})

        return StreamingResponse(_sse_generator(_gen()), media_type="text/event-stream", headers=_sse_headers())

    except BilibiliSubtitleUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 总结失败: {str(e)}")


# ──── 辅助函数 ────


def _quick_db_subtitle_check(url: str) -> bool:
    """纯 DB 检查：是否有已缓存的字幕（不含网络调用，立即返回）。"""
    from core.pipeline.subtitle import get_subtitle_from_db
    cached_sub = get_subtitle_from_db(url)
    if cached_sub and len(cached_sub["full_text"].strip()) >= 50:
        return True
    return False


def _quick_subtitle_check(url: str, info, lang: str = None, fingerprint: str = None) -> bool | None:
    """完整快速检查：DB 缓存 + B站 CC + yt-dlp 原生字幕（需要完整 info，含网络调用）。

    返回 True 表示有快速字幕源，False 表示需要 Whisper。
    """
    from core.pipeline.subtitle import get_subtitle_from_db, extract_bvid
    from core.summarizer import extract_bilibili_subtitle_by_cid
    from core.cache import get_whisper_cache

    # 1. DB 缓存
    cached_sub = get_subtitle_from_db(url)
    if cached_sub and len(cached_sub["full_text"].strip()) >= 50:
        return True

    # 2. B站 CC 字幕（快速 API 调用，不下载音频）
    bilibili_lookup_unavailable = False
    if 'bilibili' in (info.extractor or '').lower():
        p_match = re.search(r'[?&]p=(\d+)', url)
        parts = getattr(info, 'parts', []) or []
        if p_match and len(parts) > 1:
            p_index = int(p_match.group(1))
            part = next((p for p in parts if p.index == p_index), None)
            if part and part.cid:
                bvid = extract_bvid(url)
                if bvid:
                    try:
                        bilibili_sub = extract_bilibili_subtitle_by_cid(bvid, part.cid)
                        if bilibili_sub and bilibili_sub.get('has_subtitle'):
                            return True
                        if bilibili_sub is None:
                            bilibili_lookup_unavailable = True
                    except Exception:
                        bilibili_lookup_unavailable = True
            else:
                bilibili_lookup_unavailable = True
        else:
            from core.pipeline.subtitle import try_get_bilibili_cc_subtitle as _try_cc
            try:
                bilibili_sub = _try_cc(url)
                if bilibili_sub and bilibili_sub.get('has_subtitle'):
                    return True
                if bilibili_sub is None:
                    bilibili_lookup_unavailable = True
            except Exception:
                bilibili_lookup_unavailable = True

    # 3. yt-dlp 原生字幕（只检查列表，不下载）
    if info.subtitles:
        from core.pipeline.subtitle import _select_subtitle_lang
        selected = _select_subtitle_lang(info.subtitles, lang)
        if selected and selected.lang != 'danmaku':
            return True

    return None if bilibili_lookup_unavailable else False


def _try_long_video_fast_path(url: str, cached_info: dict, identity: dict):
    """超长视频快速路径：尝试 B站 CC 字幕，无则基于简介生成。"""
    from core.pipeline.subtitle import try_get_bilibili_cc_subtitle as _try_cc

    bilibili_sub = _try_cc(url, cached_info)
    if bilibili_sub and bilibili_sub.get('has_subtitle'):
        return None  # 有 CC 字幕，走正常管线
    if is_bilibili_video(url, cached_info) and bilibili_sub is None:
        raise HTTPException(
            status_code=503,
            detail="B站字幕接口暂时不可用，请稍后重试；未生成简介总结，也未启动语音转录",
        )

    _long_video_msg = f"视频时长超过 {WHISPER_MAX_DURATION} 秒限制，不支持语音识别"
    desc = cached_info.get("description", "")
    title = cached_info.get("title", "")
    duration = video_duration_for_url(url, cached_info)
    _is_bili = is_bilibili_video(url, cached_info)
    _no_cc_msg = "该B站视频没有CC字幕，" if _is_bili else ""
    if not desc or len(desc.strip()) < 20:
        raise HTTPException(status_code=400, detail=f"{_no_cc_msg}{_long_video_msg}。该视频也没有简介，无法生成 AI 总结")

    def _gen():
        yield PipelineEvent("warn", {"message": f"{_no_cc_msg}视频时长 {int(duration)} 秒超过 {WHISPER_MAX_DURATION} 秒限制，跳过语音识别"})
        yield PipelineEvent("progress", {"stage": "summary_generating", "message": "正在基于视频简介生成总结..."})
        result = summarize_from_description(title, desc)
        validate_summary_result(result)
        result["summary"] = f"⚠️ {_no_cc_msg}{_long_video_msg}，以下总结基于视频简介生成，仅供参考。\n\n" + result.get("summary", "")
        log_usage(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
                  action="summary", status="SUCCESS")
        yield PipelineEvent("result", result)
        yield PipelineEvent("done", {})

    return StreamingResponse(_sse_generator(_gen()), media_type="text/event-stream", headers=_sse_headers())


def _handle_no_subtitle(info, identity: dict):
    """无字幕降级：基于简介生成。"""
    _is_bili = 'bilibili' in (info.extractor or '').lower()
    _no_cc_msg = "该B站视频没有CC字幕，" if _is_bili else ""

    if not info.description or len(info.description.strip()) < 20:
        raise HTTPException(status_code=400, detail=f"{_no_cc_msg}该视频没有字幕也没有简介，无法生成 AI 总结")

    def _gen():
        yield PipelineEvent("warn", {"message": f"{_no_cc_msg}该视频无字幕，将基于视频简介生成总结"})
        yield PipelineEvent("progress", {"stage": "summary_generating", "message": "正在基于视频简介生成总结..."})
        result = summarize_from_description(info.title, info.description)
        validate_summary_result(result)
        result["summary"] = "⚠️ 该视频无字幕，以下总结基于视频简介生成，仅供参考。\n\n" + result.get("summary", "")
        log_usage(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
                  action="summary", status="SUCCESS")
        yield PipelineEvent("result", result)
        yield PipelineEvent("done", {})

    return StreamingResponse(_sse_generator(_gen()), media_type="text/event-stream", headers=_sse_headers())


async def _handle_partial(req, cached: dict, identity: dict, url: str, trace_id: str):
    """部分重新生成（mode != full）。"""
    # 字幕重新转录
    if req.mode == "subtitle":
        return await _partial_subtitle(req, cached, identity, url, trace_id)

    if not cached or not cached.get("subtitle_text"):
        raise HTTPException(status_code=400, detail="尚无 AI 分析缓存，请先生成完整总结")

    subtitle_text = cached["subtitle_text"]
    video_title = cached.get("video_title", "")
    cached_info = get_video_info_cache(url)
    fp = None
    cache_url = url
    if cached_info:
        video_title = cached_info.get("title", video_title) or video_title
        fp = cached_info.get("fingerprint")
    else:
        try:
            info = downloader.parse_info(url)
            cache_url = canonical_video_url(url, info)
            info.webpage_url = cache_url
            fp = video_fingerprint(info.extractor, info.id) if info.extractor and info.id else None
            video_title = info.title or video_title
        except Exception:
            pass  # parse_info 失败，继续使用已有缓存信息

    old_result = json.loads(cached["result_json"]) if cached.get("result_json") else {}

    def _gen():
        from core.cache import _max_prompt_version

        usage_action = None
        if req.mode == "summary":
            yield PipelineEvent("progress", {"stage": "summary_generating", "message": "正在重新生成 AI 摘要..."})
            result_data = {}
            for event in run_summary(subtitle_text, video_title, trace_id):
                yield event
                if event.type == "result":
                    result_data = event.data
            validate_summary_result(result_data)
            merged = {**old_result, "result": result_data}
            required_value = result_data.get("summary")
            artifact_name = "summary"
            usage_action = "summary"

        elif req.mode == "mindmap":
            yield PipelineEvent("progress", {"stage": "mindmap_generating", "message": "正在重新生成思维导图..."})
            mindmap_md = run_mindmap(subtitle_text, video_title, trace_id)
            yield PipelineEvent("mindmap", {"markdown": mindmap_md})
            merged = {**old_result, "mindmap_markdown": mindmap_md}
            required_value = mindmap_md
            artifact_name = "mindmap"

        elif req.mode == "notes":
            yield PipelineEvent("progress", {"stage": "notes_generating", "message": "正在重新生成学习笔记..."})
            notes_full = ""
            for event in run_notes(subtitle_text, video_title, cache_url, trace_id):
                yield event
                if event.type == "notes_text":
                    notes_full += event.data.get("text", "")
            merged = {**old_result, "notes": notes_full}
            required_value = notes_full
            artifact_name = "notes"
        else:
            yield PipelineEvent("error", {"message": f"未知模式: {req.mode}"})
            yield PipelineEvent("done", {})
            return

        _pi = _build_part_info(cache_url)
        commit_cached_generation(
            url=cache_url,
            video_title=video_title,
            subtitle_text=subtitle_text,
            source=cached.get("source", "cache"),
            result=merged,
            required_value=required_value,
            artifact_name=artifact_name,
            fingerprint=fp,
            part_info=cached.get("part_info") or _pi,
            platform=cached.get("platform", ""),
            prompt_version=_max_prompt_version(),
            user_id=identity.get("user_id"),
            guest_id=identity.get("guest_id"),
            usage_action=usage_action,
        )
        yield PipelineEvent("done", {})

    return StreamingResponse(_sse_generator(_gen()), media_type="text/event-stream", headers=_sse_headers())


async def _partial_subtitle(req, cached: dict, identity: dict, url: str, trace_id: str):
    """字幕重新转录（Whisper）。"""
    if not is_whisper_available():
        raise HTTPException(status_code=503, detail="feature_unavailable: Whisper 功能不可用（faster-whisper 未安装或模型未就绪）")

    cached_info = get_video_info_cache(url)
    fp = cached_info.get("fingerprint") if cached_info else None
    cache_url = url
    video_title = ""
    job_info = cached_info
    if cached_info:
        video_title = cached_info.get("title", "")
    else:
        try:
            info = downloader.parse_info(url)
            fp = video_fingerprint(info.extractor, info.id) if info.extractor and info.id else None
            cache_url = canonical_video_url(url, info)
            info.webpage_url = cache_url
            video_title = info.title or ""
            job_info = info
        except Exception:
            pass  # parse_info 失败，继续使用已有缓存信息

    duration = video_duration_for_url(cache_url, cached_info or job_info)
    job = enqueue_whisper_job(
        url_hash=_url_hash(cache_url),
        url=cache_url,
        identity=identity,
        lang=req.lang,
        estimated_seconds=estimate_transcribe_time(duration),
        info=job_info,
        fingerprint=fp,
        pipeline="subtitle_only",
    )

    def _gen():
        yield PipelineEvent("background_started", {
            "task_id": job["task_id"],
            "url_hash": job["url_hash"],
            "estimated_seconds": job["estimated_seconds"],
            "queue_position": job["queue_position"],
            "message": "字幕重转录已加入后台队列",
        })
        yield PipelineEvent("done", {})

    return StreamingResponse(_sse_generator(_gen()), media_type="text/event-stream", headers=_sse_headers())


# ──── AI 问答 ────

@router.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, request: Request):
    """SSE 流式 AI 问答。"""
    if not is_ai_available():
        raise HTTPException(status_code=503, detail="feature_unavailable: AI 功能不可用（SDK 未安装、未启用或未配置 API Key）")
    if not req.subtitle_text or len(req.subtitle_text.strip()) < 10:
        raise HTTPException(status_code=400, detail="字幕内容为空，无法进行问答")

    identity = require_identity(request)
    allowed, used, limit = check_usage_limit(
        identity.get("user_id"), identity.get("guest_id"), identity.get("guest_sig")
    )
    if not allowed:
        raise HTTPException(status_code=429, detail=f"今日 AI 次数已用完（{used}/{limit}）")

    try:
        def _gen():
            for event_type, data in stream_chat(req.subtitle_text, req.question, [h.model_dump() for h in req.history]):
                yield PipelineEvent(event_type, data)
            log_usage(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
                      action="qa", status="SUCCESS")
            yield PipelineEvent("done", {})

        return StreamingResponse(_sse_generator(_gen()), media_type="text/event-stream", headers=_sse_headers())

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"问答失败: {str(e)}")


# ──── AI 关键问答对生成 ────

def _merge_and_save_qanda(
    url: str,
    subtitle_text: str,
    video_title: str,
    qa_pairs: list,
    identity: dict,
):
    """将问答对合并写入已有缓存（保留 summary/mindmap/notes）。"""
    existing_raw = _get_cached_raw(url)
    result_json = {}
    fingerprint = None
    platform = ""
    source = "cache"

    if existing_raw:
        if existing_raw.get("result_json"):
            try:
                result_json = json.loads(existing_raw["result_json"])
            except json.JSONDecodeError:
                result_json = {}
        fingerprint = existing_raw.get("fingerprint")
        platform = existing_raw.get("platform", "")
        source = existing_raw.get("source", "cache")

    result_json["qa_pairs"] = qa_pairs

    from core.cache import _max_prompt_version
    commit_cached_generation(
        url=url,
        video_title=video_title or (existing_raw.get("video_title", "") if existing_raw else ""),
        subtitle_text=subtitle_text or (existing_raw.get("subtitle_text", "") if existing_raw else ""),
        source=source,
        result=result_json,
        required_value=qa_pairs,
        artifact_name="qanda",
        fingerprint=fingerprint,
        part_info=existing_raw.get("part_info", "") if existing_raw else "",
        platform=platform,
        prompt_version=_max_prompt_version(),
        user_id=identity.get("user_id"),
        guest_id=identity.get("guest_id"),
        usage_action="qanda",
    )


@router.post("/api/qa/stream")
async def qa_stream(req: QaGenerationRequest, request: Request):
    """SSE 流式 AI 关键问答对生成（支持缓存）。"""
    if not is_ai_available():
        raise HTTPException(status_code=503, detail="feature_unavailable: AI 功能不可用（SDK 未安装、未启用或未配置 API Key）")
    if not req.subtitle_text or len(req.subtitle_text.strip()) < 10:
        raise HTTPException(status_code=400, detail="字幕内容为空，无法生成问答")

    identity = require_identity(request)

    # ── 缓存检查 ──
    if req.url and not req.force:
        cached = get_cached(req.url)
        if cached and cached.get("result_json"):
            try:
                result_data = json.loads(cached["result_json"])
                if result_data.get("qa_pairs"):
                    def _replay():
                        yield PipelineEvent("progress", {"stage": "cache_hit", "message": "已有问答缓存，直接加载"})
                        yield PipelineEvent("qa_pairs", result_data["qa_pairs"])
                        yield PipelineEvent("done", {})
                    return StreamingResponse(_sse_generator(_replay()), media_type="text/event-stream", headers=_sse_headers())
            except json.JSONDecodeError:
                pass

    # ── AI 使用次数检查 ──
    allowed, used, limit = check_usage_limit(
        identity.get("user_id"), identity.get("guest_id"), identity.get("guest_sig")
    )
    if not allowed:
        raise HTTPException(status_code=429, detail=f"今日 AI 次数已用完（{used}/{limit}）")

    trace_id = uuid.uuid4().hex[:8]

    try:
        def _gen():
            qa_pairs_result = []
            for event in run_qanda(req.subtitle_text, req.video_title, trace_id):
                yield event
                if event.type == "qa_pairs":
                    qa_pairs_result = event.data

            if not qa_pairs_result:
                raise InvalidGenerationResult("qanda result is empty")
            if req.url:
                _merge_and_save_qanda(
                    req.url,
                    req.subtitle_text,
                    req.video_title,
                    qa_pairs_result,
                    identity,
                )
            else:
                try:
                    json.dumps(qa_pairs_result, ensure_ascii=False, allow_nan=False)
                except (TypeError, ValueError) as exc:
                    raise InvalidGenerationResult("qanda result is not JSON serializable") from exc
                log_usage(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
                          action="qanda", status="SUCCESS")
            yield PipelineEvent("done", {})

        return StreamingResponse(_sse_generator(_gen()), media_type="text/event-stream", headers=_sse_headers())

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"问答对生成失败: {str(e)}")
