"""SSE 流式端点 — /api/summarize/stream + /api/chat/stream。

所有 SSE 端点返回 text/event-stream，事件格式: data: {"type":"...","data":{...}}\n\n
"""

import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from core.summary_models import SummarizeRequest, SummaryResult, ChapterItem, MindMapNode, ChatRequest
from core.summarizer import (
    clean_subtitle_text, _clean_danmaku_xml,
    summarize_from_description,
    extract_bilibili_subtitle,
)
from core.ai_client import (
    stream_summarize, stream_chat, stream_generate_notes,
    generate_mindmap, correct_subtitle,
)
from config import SUBTITLE_CORRECTION_ENABLED, WHISPER_MAX_DURATION
from core.cache import get_cached, save_cache, get_whisper_cache, save_whisper_cache, get_video_info_cache, save_video_info_cache
from core.whisper import transcribe_video, is_model_available

from api.routes import extract_url, _download_subtitle_content, downloader
from api.summary_routes import (
    _select_subtitle_lang, inc_summarize_usage,
)

router = APIRouter()


async def _sse_generator(sync_gen):
    """将同步 (event_type, data) generator 转为 SSE 字节流。
    使用 asyncio.Queue 实现真正的实时流式传输，不再缓冲。"""
    loop = asyncio.get_event_loop()
    queue = asyncio.Queue()

    def _run():
        try:
            for event_type, data in sync_gen:
                payload = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
                loop.call_soon_threadsafe(queue.put_nowait, payload)
        except Exception as e:
            payload = json.dumps({"type": "error", "data": {"message": str(e)}}, ensure_ascii=False)
            loop.call_soon_threadsafe(queue.put_nowait, payload)
        loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(None, _run)

    while True:
        payload = await queue.get()
        if payload is None:
            break
        yield f"data: {payload}\n\n".encode("utf-8")


# ──── 字幕获取 Pipeline ────

async def _get_subtitle_text(url: str, info, lang: str = None) -> tuple[str, str, str]:
    """标准化字幕获取：
       1. 平台 API（B站 CC / YouTube auto-captions）
       2. yt-dlp 原生字幕
       3. Whisper fallback（预留）

    返回 (subtitle_text, source, language)
    """
    # Pipeline 1: Bilibili CC 字幕 API
    bilibili_sub = extract_bilibili_subtitle(url)
    if bilibili_sub and bilibili_sub['has_subtitle']:
        return bilibili_sub['full_text'], "bilibili_cc", bilibili_sub.get('language', 'zh')

    # Pipeline 2: yt-dlp 原生字幕
    if info.subtitles:
        selected = _select_subtitle_lang(info.subtitles, lang)
        if selected and selected.lang != 'danmaku':
            try:
                raw_content, ext = await asyncio.get_event_loop().run_in_executor(
                    None, _download_subtitle_content, url, selected.lang, selected.is_auto
                )
                if ext == 'xml' or selected.lang == 'danmaku':
                    subtitle_text = _clean_danmaku_xml(raw_content)
                else:
                    subtitle_text = clean_subtitle_text(raw_content, ext)
                if subtitle_text and len(subtitle_text.strip()) >= 50:
                    source = "youtube_auto" if selected.is_auto else "ytdlp_native"
                    return subtitle_text, source, selected.lang
            except Exception:
                pass

    # Pipeline 3: Whisper 转录（兜底）
    if is_model_available():
        # 视频时长超过限制，跳过 Whisper（CPU 转录太慢）
        if info.duration and info.duration > WHISPER_MAX_DURATION:
            return None, "", ""
        # 先查 Whisper 缓存，避免重复转录
        cached_whisper = get_whisper_cache(url)
        if cached_whisper and len(cached_whisper.strip()) >= 20:
            return cached_whisper, "whisper", lang or "auto"

        try:
            whisper_text = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, transcribe_video, url, lang),
                timeout=600,
            )
            if whisper_text and len(whisper_text.strip()) >= 20:
                # AI 校正 Whisper 转录文本
                corrected = whisper_text
                if SUBTITLE_CORRECTION_ENABLED:
                    try:
                        corrected = await asyncio.wait_for(
                            asyncio.get_event_loop().run_in_executor(
                                None, correct_subtitle, whisper_text, info.title, info.description
                            ),
                            timeout=60,
                        )
                    except (asyncio.TimeoutError, Exception) as e:
                        print(f"[SubtitleCorrection] 校正失败，使用原始文本: {e}")
                        corrected = whisper_text
                save_whisper_cache(url, corrected, lang or "auto", whisper_text)
                return corrected, "whisper", lang or "auto"
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass

    # Pipeline 4: OCR 硬字幕（预留接口）
    return None, "", ""


@router.post("/api/summarize/stream")
async def summarize_stream(req: SummarizeRequest):
    """SSE 流式 AI 视频总结。"""
    try:
        url = extract_url(req.url)

        # ── 缓存检查 ──
        cached = get_cached(url)
        if cached and cached.get("result_json"):
            result_data = json.loads(cached["result_json"])

            def _replay():
                yield ("progress", {"stage": "cache_hit", "message": "已有学习记录，直接加载"})
                result = result_data.get("result", {})
                if result:
                    yield ("result", result)
                if result_data.get("mindmap_markdown"):
                    yield ("mindmap", {"markdown": result_data["mindmap_markdown"]})
                if result_data.get("notes"):
                    # 流式重放笔记内容（模拟流式体验）
                    yield ("notes", {"markdown": result_data["notes"]})
                if result_data.get("flashcards"):
                    yield ("flashcards", result_data["flashcards"])
                yield ("done", {})

            return StreamingResponse(
                _sse_generator(_replay()),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )

        # ── 视频信息缓存预检（快速路径：已缓存的超长视频直接跳过） ──
        cached_info = get_video_info_cache(url)
        _long_video_msg = f"视频时长超过 {WHISPER_MAX_DURATION} 秒限制，不支持语音识别"

        if cached_info and cached_info.get("duration", 0) > WHISPER_MAX_DURATION:
            desc = cached_info.get("description", "")
            title = cached_info.get("title", "")
            duration = cached_info.get("duration", 0)
            if not desc or len(desc.strip()) < 20:
                raise HTTPException(status_code=400, detail=f"{_long_video_msg}。该视频也没有简介，无法生成 AI 总结")

            def _gen_desc_fast():
                yield ("warn", {"message": f"视频时长 {int(duration)} 秒超过 {WHISPER_MAX_DURATION} 秒限制，跳过语音识别"})
                yield ("progress", {"stage": "summary_generating", "message": "正在基于视频简介生成总结..."})
                result = summarize_from_description(title, desc)
                inc_summarize_usage()
                result["summary"] = f"⚠️ {_long_video_msg}，以下总结基于视频简介生成，仅供参考。\n\n" + result.get("summary", "")
                yield ("result", result)
                yield ("done", {})

            return StreamingResponse(
                _sse_generator(_gen_desc_fast()),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )

        # ── 解析视频信息 ──
        info = downloader.parse_info(url)
        save_video_info_cache(url, info)

        # ── 字幕获取（在 async 上下文中执行） ──
        subtitle_text, sub_source, sub_lang = await _get_subtitle_text(url, info, req.lang)

        # ── 无字幕降级 ──
        if not subtitle_text:
            if not info.description or len(info.description.strip()) < 20:
                if info.duration and info.duration > WHISPER_MAX_DURATION:
                    raise HTTPException(status_code=400, detail=f"视频时长 {int(info.duration)} 秒，超过 {WHISPER_MAX_DURATION} 秒限制，不支持语音识别。请尝试有字幕的视频")
                raise HTTPException(status_code=400, detail="该视频没有字幕也没有简介，无法生成 AI 总结")

            def _gen_no_sub():
                if info.duration and info.duration > WHISPER_MAX_DURATION:
                    yield ("warn", {"message": f"视频时长 {int(info.duration)} 秒超过 {WHISPER_MAX_DURATION} 秒限制，跳过语音识别"})
                else:
                    yield ("warn", {"message": "该视频无字幕，将基于视频简介生成总结"})
                yield ("progress", {"stage": "summary_generating", "message": "正在基于视频简介生成总结..."})
                result = summarize_from_description(info.title, info.description)
                inc_summarize_usage()
                result["summary"] = "⚠️ 该视频无字幕，以下总结基于视频简介生成，仅供参考。\n\n" + result.get("summary", "")
                yield ("result", result)
                yield ("done", {})

            return StreamingResponse(
                _sse_generator(_gen_no_sub()),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )

        # ── 正常 AI 流水线 ──
        def _gen():
            source_label = {
                "bilibili_cc": "B站CC字幕",
                "youtube_auto": "YouTube自动字幕",
                "ytdlp_native": "平台原生字幕",
                "whisper": "Whisper语音识别",
            }.get(sub_source, sub_source)

            yield ("progress", {
                "stage": "subtitle_loaded",
                "source": sub_source,
                "lang": sub_lang,
                "message": f"字幕就绪（{source_label}），开始 AI 分析...",
            })

            # 1. AI 摘要（流式）
            yield ("progress", {"stage": "summary_generating", "message": "正在生成 AI 摘要..."})
            has_error = False
            result_data = {}
            for event_type, data in stream_summarize(subtitle_text, info.title):
                yield (event_type, data)
                if event_type == "error":
                    has_error = True
                    break
                if event_type == "result":
                    result_data = data

            if has_error:
                yield ("done", {})
                return

            inc_summarize_usage()

            # 2. 思维导图
            yield ("progress", {"stage": "mindmap_generating", "message": "正在构建思维导图..."})
            mindmap_md = ""
            try:
                mindmap_md = generate_mindmap(subtitle_text, info.title)
                yield ("mindmap", {"markdown": mindmap_md})
            except Exception as e:
                yield ("warn", {"message": f"思维导图生成失败: {str(e)}"})

            # 3. 学习笔记（流式）
            yield ("progress", {"stage": "notes_generating", "message": "正在生成学习笔记..."})
            notes_full = ""
            try:
                for event_type, data in stream_generate_notes(subtitle_text, info.title):
                    yield (event_type, data)
                    if event_type == "notes_text":
                        notes_full += data.get("text", "")
            except Exception as e:
                yield ("warn", {"message": f"笔记生成失败: {str(e)}"})

            # ── 持久化 ──
            save_cache_json = json.dumps({
                "result": result_data,
                "mindmap_markdown": mindmap_md,
                "notes": notes_full,
            }, ensure_ascii=False)
            save_cache(url, info.title, subtitle_text, sub_source, save_cache_json)

            yield ("done", {})

        return StreamingResponse(
            _sse_generator(_gen()),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 总结失败: {str(e)}")


@router.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE 流式 AI 问答。"""
    if not req.subtitle_text or len(req.subtitle_text.strip()) < 10:
        raise HTTPException(status_code=400, detail="字幕内容为空，无法进行问答")

    try:
        def _gen():
            for event_type, data in stream_chat(req.subtitle_text, req.question, [h.model_dump() for h in req.history]):
                yield (event_type, data)
            yield ("done", {})

        return StreamingResponse(
            _sse_generator(_gen()),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"问答失败: {str(e)}")
