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
    stream_summarize, stream_chat,
    summarize_from_description,
    extract_bilibili_subtitle,
    generate_mindmap_markdown,
)

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


@router.post("/api/summarize/stream")
async def summarize_stream(req: SummarizeRequest):
    """SSE 流式 AI 视频总结。"""
    try:
        url = extract_url(req.url)
        info = downloader.parse_info(url)

        # 优先尝试 Bilibili CC 字幕 API
        subtitle_text = None
        bilibili_sub = extract_bilibili_subtitle(url)
        if bilibili_sub and bilibili_sub['has_subtitle']:
            subtitle_text = bilibili_sub['full_text']

        # 降级：通过 yt-dlp 获取字幕
        selected = None
        if not subtitle_text and info.subtitles:
            selected = _select_subtitle_lang(info.subtitles, req.lang)
            if selected and selected.lang != 'danmaku':
                try:
                    raw_content, ext = await asyncio.get_event_loop().run_in_executor(
                        None, _download_subtitle_content, url, selected.lang, selected.is_auto
                    )
                    if ext == 'xml' or selected.lang == 'danmaku':
                        subtitle_text = _clean_danmaku_xml(raw_content)
                    else:
                        subtitle_text = clean_subtitle_text(raw_content, ext)
                    if subtitle_text and len(subtitle_text.strip()) < 50:
                        subtitle_text = None
                except Exception:
                    subtitle_text = None

        # 无字幕：降级到视频简介
        if not subtitle_text:
            if not info.description or len(info.description.strip()) < 20:
                raise HTTPException(status_code=400, detail="该视频没有字幕也没有简介，无法生成 AI 总结")

            def _gen():
                yield ("warn", {"message": "该视频无字幕，将基于视频简介生成总结"})
                result = summarize_from_description(info.title, info.description)
                inc_summarize_usage()
                result["summary"] = "⚠️ 该视频无字幕，以下总结基于视频简介生成，仅供参考。\n\n" + result.get("summary", "")
                yield ("result", result)
                yield ("done", {})

            return StreamingResponse(
                _sse_generator(_gen()),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )

        sub_source = "bilibili_cc" if (bilibili_sub and bilibili_sub['has_subtitle']) else "ytdlp"
        sub_lang = bilibili_sub.get('language', '') if (bilibili_sub and bilibili_sub['has_subtitle']) else (selected.lang if selected else '')

        def _gen():
            yield ("progress", {"stage": "subtitle_loaded", "source": sub_source, "lang": sub_lang, "message": "字幕加载完成，正在生成 AI 总结..."})

            has_error = False
            for event_type, data in stream_summarize(subtitle_text, info.title):
                yield (event_type, data)
                if event_type == "error":
                    has_error = True
                    break

            if not has_error:
                inc_summarize_usage()

                # 单独生成思维导图 Markdown
                try:
                    mindmap_md = generate_mindmap_markdown(subtitle_text, info.title)
                    yield ("mindmap", {"markdown": mindmap_md})
                except Exception as e:
                    yield ("warn", {"message": f"思维导图生成失败: {str(e)}"})

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
