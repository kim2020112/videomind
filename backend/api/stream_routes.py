"""SSE 流式端点 — /api/summarize/stream + /api/chat/stream。

所有 SSE 端点返回 text/event-stream，事件格式: data: {"type":"...","data":{...}}\n\n
"""

import asyncio
import json
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from core.summary_models import SummarizeRequest, SummaryResult, ChapterItem, MindMapNode, ChatRequest
from core.summarizer import (
    clean_subtitle_text, _clean_danmaku_xml,
    summarize_from_description,
    extract_bilibili_subtitle,
    extract_bilibili_subtitle_by_cid,
)
from core.ai_client import (
    stream_summarize, stream_chat, stream_generate_notes,
    generate_mindmap, correct_subtitle,
    stream_chunk_summaries, _split_text,
    inject_notes_timestamps,
)
from config import SUBTITLE_CORRECTION_ENABLED, WHISPER_MAX_DURATION
from core.cache import get_cached, save_cache, delete_cache, delete_whisper_cache, get_whisper_cache, save_whisper_cache, get_video_info_cache, save_video_info_cache, video_fingerprint
from core.whisper import transcribe_video_async, is_model_available
from core.tag_extractor import extract_tags, detect_platform

from api.routes import extract_url, _download_subtitle_content, downloader
from api.summary_routes import (
    _select_subtitle_lang, inc_summarize_usage,
)

router = APIRouter()


def _build_part_info(url: str, info=None, parts: list = None) -> str:
    """从 URL 和视频信息构建分P描述（如 'P2: 第一章-01-什么是Agent'）。"""
    p_match = re.search(r'[?&]p=(\d+)', url)
    if not p_match:
        return ""
    p_index = int(p_match.group(1))
    # 从 info.parts 或 parts 列表中查找
    part_list = parts or (getattr(info, 'parts', None) or []) if info else []
    def _get(obj, attr):
        return obj.get(attr) if isinstance(obj, dict) else getattr(obj, attr, None)
    part = next((p for p in part_list if _get(p, 'index') == p_index), None)
    if part:
        title = _get(part, 'title') or ''
        if title:
            return f"P{p_index}: {title}"
    return f"P{p_index}"


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

async def _get_subtitle_text(url: str, info, lang: str = None, fingerprint: str = None) -> tuple[str, str, str]:
    """标准化字幕获取（DB 优先，减少重复 API 调用）：
       1. 平台 API（B站 CC / YouTube auto-captions）
       2. yt-dlp 原生字幕
       3. Whisper fallback

    返回 (subtitle_text, source, language)
    """
    from database import get_subtitle_from_db, save_subtitle_to_db
    platform = info.extractor or ""

    # ── DB 缓存检查 ──
    cached_sub = get_subtitle_from_db(url)
    if cached_sub and len(cached_sub["full_text"].strip()) >= 50:
        # 补全缺失的 title/platform/part_info
        _pi = _build_part_info(url, info=info)
        save_subtitle_to_db(url, cached_sub["source"], cached_sub["language"], cached_sub["full_text"], info.title, platform, part_info=_pi)
        return cached_sub["full_text"], cached_sub["source"], cached_sub["language"]

    # ── Pipeline 1: Bilibili CC 字幕 API ──
    bilibili_sub = None
    if 'bilibili' in (info.extractor or '').lower():
        # 多P视频：用指定分P的 cid 获取字幕
        p_match = re.search(r'[?&]p=(\d+)', url)
        parts = getattr(info, 'parts', []) or []
        if p_match and len(parts) > 1:
            p_index = int(p_match.group(1))
            part = next((p for p in parts if p.index == p_index), None)
            if part and part.cid:
                bvid_m = re.search(r'(BV\w+)', url)
                if bvid_m:
                    bilibili_sub = extract_bilibili_subtitle_by_cid(bvid_m.group(1), part.cid)
        else:
            bilibili_sub = extract_bilibili_subtitle(url)
    if bilibili_sub and bilibili_sub['has_subtitle']:
        text = bilibili_sub['full_text']
        sub_lang = bilibili_sub.get('language', 'zh')
        _pi = _build_part_info(url, info=info)
        save_subtitle_to_db(url, "bilibili_cc", sub_lang, bilibili_sub['text'], info.title, platform, part_info=_pi)
        return text, "bilibili_cc", sub_lang

    # ── Pipeline 2: yt-dlp 原生字幕 ──
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
                    _pi = _build_part_info(url, info=info)
                    save_subtitle_to_db(url, source, selected.lang, subtitle_text, info.title, platform, part_info=_pi)
                    return subtitle_text, source, selected.lang
            except Exception:
                pass

    # ── Pipeline 3: Whisper 转录（兜底） ──
    if is_model_available():
        if info.duration and info.duration > WHISPER_MAX_DURATION:
            return None, "", ""
        cached_whisper = get_whisper_cache(url, fingerprint=fingerprint)
        if cached_whisper and len(cached_whisper.strip()) >= 20:
            _pi = _build_part_info(url, info=info)
            save_subtitle_to_db(url, "whisper", lang or "auto", cached_whisper, info.title, platform, part_info=_pi)
            return cached_whisper, "whisper", lang or "auto"

        try:
            whisper_text = await asyncio.wait_for(
                transcribe_video_async(url, lang),
                timeout=600,
            )
            if whisper_text and len(whisper_text.strip()) >= 20:
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
                save_whisper_cache(url, corrected, lang or "auto", whisper_text, fingerprint=fingerprint)
                _pi = _build_part_info(url, info=info)
                save_subtitle_to_db(url, "whisper", lang or "auto", corrected, info.title, platform, part_info=_pi)
                return corrected, "whisper", lang or "auto"
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass

    return None, "", ""


@router.post("/api/summarize/stream")
async def summarize_stream(req: SummarizeRequest):
    """SSE 流式 AI 视频总结。"""
    try:
        url = extract_url(req.url)

        # ── 缓存检查 ──
        cached = get_cached(url)
        if req.force:
            if cached:
                if req.mode == "full":
                    delete_cache(url)
                    cached = None
                # 非 full 模式 force：只清除对应组件，保留其他缓存
            elif req.mode != "full":
                raise HTTPException(status_code=400, detail="尚无缓存，请先生成完整 AI 总结")

        if cached and cached.get("result_json") and req.mode == "full" and not req.force:
            result_data = json.loads(cached["result_json"])
            # 确保 videos 表有记录（历史记录依赖此表）
            from database import save_subtitle_to_db as _save_sub
            _save_sub(url, cached.get("source", ""), "", cached.get("subtitle_text", ""),
                      cached.get("video_title", ""), part_info=cached.get("part_info", ""))

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

        # ── 部分重新生成（mode != "full"）：从缓存取字幕，只跑指定组件 ──
        if req.mode != "full":
            # 字幕重新转录特殊处理：不需要已有缓存
            if req.mode == "subtitle":
                if not is_model_available():
                    raise HTTPException(status_code=400, detail="Whisper 模型未就绪，无法转录")

                cached_info = get_video_info_cache(url)
                fp = cached_info.get("fingerprint") if cached_info else None
                cache_url = url
                if cached_info:
                    video_title = cached_info.get("title", "")
                else:
                    try:
                        info = downloader.parse_info(url)
                        fp = video_fingerprint(info.extractor, info.id) if info.extractor and info.id else None
                        cache_url = info.webpage_url or url
                        save_video_info_cache(cache_url, info, fingerprint=fp)
                        video_title = info.title or ""
                    except Exception:
                        video_title = ""

                # 先删除旧 Whisper 缓存
                delete_whisper_cache(cache_url, fingerprint=fp)

                # 在 async 上下文中执行转录（不能在 sync generator 中用 await）
                whisper_text = ""
                whisper_error = ""
                try:
                    whisper_text = await asyncio.wait_for(
                        transcribe_video_async(url, req.lang), timeout=600
                    )
                except Exception as e:
                    whisper_error = str(e)

                corrected = ""
                if whisper_text and len(whisper_text.strip()) >= 20:
                    corrected = whisper_text
                    if SUBTITLE_CORRECTION_ENABLED:
                        try:
                            corrected = await asyncio.wait_for(
                                asyncio.get_event_loop().run_in_executor(
                                    None, correct_subtitle, whisper_text, video_title, ""
                                ),
                                timeout=60,
                            )
                        except Exception:
                            corrected = whisper_text
                    save_whisper_cache(cache_url, corrected, req.lang or "auto", whisper_text, fingerprint=fp)
                    if cached and cached.get("result_json"):
                        _pi = _build_part_info(cache_url, info=locals().get('info'), parts=(cached_info or {}).get('parts'))
                        save_cache(cache_url, video_title, corrected, "whisper", cached["result_json"], fingerprint=fp, part_info=_pi)

                def _gen_subtitle():
                    yield ("progress", {"stage": "subtitle_transcribing", "message": "正在用 Whisper 重新语音识别..."})
                    if whisper_error:
                        yield ("error", {"message": f"Whisper 转录失败: {whisper_error}"})
                        yield ("done", {})
                        return
                    if not whisper_text or len(whisper_text.strip()) < 20:
                        yield ("error", {"message": "Whisper 转录结果为空或过短"})
                        yield ("done", {})
                        return
                    yield ("progress", {"stage": "subtitle_loaded", "source": "whisper", "lang": req.lang or "auto", "message": "语音识别已完成，字幕已更新"})
                    yield ("subtitle_text", {"text": corrected})
                    yield ("done", {})

                return StreamingResponse(
                    _sse_generator(_gen_subtitle()),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
                )

            if not cached or not cached.get("subtitle_text"):
                raise HTTPException(status_code=400, detail="尚无 AI 分析缓存，请先生成完整总结")
            subtitle_text = cached["subtitle_text"]
            video_title = cached.get("video_title", "")
            sub_source = "cache"
            sub_lang = ""
            cache_url = url
            fp = None
            # 从缓存用 info
            cached_info = get_video_info_cache(url)
            if cached_info:
                video_title = cached_info.get("title", video_title) or video_title
                fp = cached_info.get("fingerprint")
            else:
                # 尝试解析获取标题
                try:
                    info = downloader.parse_info(url)
                    cache_url = info.webpage_url or url
                    fp = video_fingerprint(info.extractor, info.id) if info.extractor and info.id else None
                    save_video_info_cache(cache_url, info, fingerprint=fp)
                    video_title = info.title or video_title
                except Exception:
                    pass

            old_result = json.loads(cached["result_json"]) if cached.get("result_json") else {}

            def _gen_partial():
                if req.mode == "summary":
                    yield ("progress", {"stage": "summary_generating", "message": "正在重新生成 AI 摘要..."})
                    result_data = {}
                    for event_type, data in stream_summarize(subtitle_text, video_title):
                        yield (event_type, data)
                        if event_type == "result":
                            result_data = data
                    inc_summarize_usage()
                    merged = json.dumps({**old_result, "result": result_data}, ensure_ascii=False)

                elif req.mode == "mindmap":
                    yield ("progress", {"stage": "mindmap_generating", "message": "正在重新生成思维导图..."})
                    mindmap_md = generate_mindmap(subtitle_text, video_title)
                    yield ("mindmap", {"markdown": mindmap_md})
                    merged = json.dumps({**old_result, "mindmap_markdown": mindmap_md}, ensure_ascii=False)

                elif req.mode == "notes":
                    yield ("progress", {"stage": "notes_generating", "message": "正在重新生成学习笔记..."})
                    notes_full = ""
                    for event_type, data in stream_generate_notes(subtitle_text, video_title):
                        yield (event_type, data)
                        if event_type == "notes_text":
                            notes_full += data.get("text", "")
                    merged = json.dumps({**old_result, "notes": notes_full}, ensure_ascii=False)
                else:
                    yield ("error", {"message": f"未知模式: {req.mode}"})
                    yield ("done", {})
                    return

                _pi = _build_part_info(cache_url, info=locals().get('info'), parts=(cached_info or {}).get('parts'))
                save_cache(cache_url, video_title, subtitle_text, sub_source, merged, fingerprint=fp, part_info=_pi)
                yield ("done", {})

            return StreamingResponse(
                _sse_generator(_gen_partial()),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )

        # ── 视频信息缓存预检（快速路径：已缓存的超长视频直接跳过 Whisper） ──
        cached_info = get_video_info_cache(url)
        _long_video_msg = f"视频时长超过 {WHISPER_MAX_DURATION} 秒限制，不支持语音识别"

        if cached_info and cached_info.get("duration", 0) > WHISPER_MAX_DURATION:
            # B站视频可能有 CC 字幕（独立于 yt-dlp），先尝试获取
            bilibili_sub = None
            if 'bilibili' in url.lower():
                p_match_fp = re.search(r'[?&]p=(\d+)', url)
                if p_match_fp:
                    parts_fp = cached_info.get('parts', []) or []
                    p_idx = int(p_match_fp.group(1))
                    part_fp = next((p for p in parts_fp if p.get('index') == p_idx), None)
                    if part_fp and part_fp.get('cid'):
                        bvid_fp = re.search(r'(BV\w+)', url)
                        if bvid_fp:
                            bilibili_sub = extract_bilibili_subtitle_by_cid(bvid_fp.group(1), part_fp['cid'])
            if not bilibili_sub:
                bilibili_sub = extract_bilibili_subtitle(url)
            if bilibili_sub and bilibili_sub.get('has_subtitle'):
                pass  # 有 B站 CC 字幕，跳过快速路径，走正常 AI 管线
            else:
                desc = cached_info.get("description", "")
                title = cached_info.get("title", "")
                duration = cached_info.get("duration", 0)
                _is_bili = 'bilibili' in url.lower()
                _no_cc_msg = "该B站视频没有CC字幕，" if _is_bili else ""
                if not desc or len(desc.strip()) < 20:
                    raise HTTPException(status_code=400, detail=f"{_no_cc_msg}{_long_video_msg}。该视频也没有简介，无法生成 AI 总结")

                def _gen_desc_fast():
                    yield ("warn", {"message": f"{_no_cc_msg}视频时长 {int(duration)} 秒超过 {WHISPER_MAX_DURATION} 秒限制，跳过语音识别"})
                    yield ("progress", {"stage": "summary_generating", "message": "正在基于视频简介生成总结..."})
                    result = summarize_from_description(title, desc)
                    inc_summarize_usage()
                    result["summary"] = f"⚠️ {_no_cc_msg}{_long_video_msg}，以下总结基于视频简介生成，仅供参考。\n\n" + result.get("summary", "")
                    yield ("result", result)
                    yield ("done", {})

                return StreamingResponse(
                    _sse_generator(_gen_desc_fast()),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
                )

        # ── 解析视频信息 ──
        info = downloader.parse_info(url)
        fp = video_fingerprint(info.extractor, info.id) if info.extractor and info.id else None
        canonical_url = info.webpage_url or url
        # 多P视频：确保 canonical_url 保留 ?p=N 参数（yt-dlp 可能丢弃）
        p_match = re.search(r'[?&]p=(\d+)', url)
        if p_match and not re.search(r'[?&]p=\d+', canonical_url):
            sep = '&' if '?' in canonical_url else '?'
            canonical_url = f"{canonical_url}{sep}p={p_match.group(1)}"
        save_video_info_cache(canonical_url, info, fingerprint=fp)

        # ── 二次缓存检查（同视频不同 URL 变体，按指纹命中） ──
        if not cached and fp:
            cached = get_cached(canonical_url, fingerprint=fp)
            if cached and cached.get("result_json") and req.mode == "full" and not req.force:
                result_data = json.loads(cached["result_json"])
                def _replay_fp():
                    yield ("progress", {"stage": "cache_hit", "message": "已有学习记录，直接加载"})
                    result = result_data.get("result", {})
                    if result:
                        yield ("result", result)
                    if result_data.get("mindmap_markdown"):
                        yield ("mindmap", {"markdown": result_data["mindmap_markdown"]})
                    if result_data.get("notes"):
                        yield ("notes", {"markdown": result_data["notes"]})
                    if result_data.get("flashcards"):
                        yield ("flashcards", result_data["flashcards"])
                    yield ("done", {})
                return StreamingResponse(
                    _sse_generator(_replay_fp()),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
                )

        # ── 字幕获取（在 async 上下文中执行） ──
        subtitle_text, sub_source, sub_lang = await _get_subtitle_text(canonical_url, info, req.lang, fingerprint=fp)

        # ── 无字幕降级 ──
        if not subtitle_text:
            _is_bili = 'bilibili' in (info.extractor or '').lower()
            _no_cc_msg = "该B站视频没有CC字幕，" if _is_bili else ""
            if not info.description or len(info.description.strip()) < 20:
                if info.duration and info.duration > WHISPER_MAX_DURATION:
                    raise HTTPException(status_code=400, detail=f"{_no_cc_msg}视频时长 {int(info.duration)} 秒，超过 {WHISPER_MAX_DURATION} 秒限制，不支持语音识别。请尝试有字幕的视频")
                raise HTTPException(status_code=400, detail="该视频没有字幕也没有简介，无法生成 AI 总结")

            def _gen_no_sub():
                if info.duration and info.duration > WHISPER_MAX_DURATION:
                    yield ("warn", {"message": f"{_no_cc_msg}视频时长 {int(info.duration)} 秒超过 {WHISPER_MAX_DURATION} 秒限制，跳过语音识别"})
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

        # ── 章节信息拼入字幕上下文 ──
        chapters = None
        if hasattr(info, 'chapters') and info.chapters:
            chapters = [{"start_time": ch.start_time, "end_time": ch.end_time, "title": ch.title} for ch in info.chapters]
        chapter_context = ""
        if chapters:
            chapter_lines = ["\n\n## 视频章节信息\n"]
            for ch in chapters:
                mm = int(ch["start_time"] // 60)
                ss = int(ch["start_time"] % 60)
                chapter_lines.append(f"- [{mm:02d}:{ss:02d}] {ch['title']}")
            chapter_context = "\n".join(chapter_lines)
            subtitle_text = subtitle_text + chapter_context

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

            if chapters:
                yield ("chapters", {"chapters": chapters})

            # 1. AI 摘要（流式）— 长视频首片优先
            chunks = _split_text(subtitle_text)

            if len(chunks) > 1:
                result_data = {}
                subtitle_for_rest = subtitle_text

                for cevt, cdata in stream_chunk_summaries(subtitle_text, info.title):
                    if cevt == "first_chunk_ready":
                        yield ("progress", {
                            "stage": "summary_initial",
                            "message": f"基于视频前段内容（约{100//cdata['total']}%），生成初步摘要...",
                        })
                        for sevt, sdata in stream_summarize(cdata["text"], info.title):
                            if sevt == "error":
                                yield ("done", {})
                                return
                            if sevt == "result":
                                sdata["is_partial"] = True
                                result_data = sdata
                            yield (sevt, sdata)

                    elif cevt == "chunk_progress":
                        yield ("progress", {
                            "stage": "chunk_progress",
                            "message": f"字幕片段处理中 ({cdata['index']+1}/{cdata['total']})...",
                        })

                    elif cevt == "all_chunks_ready":
                        subtitle_for_rest = cdata["text"]
                        yield ("progress", {
                            "stage": "summary_final",
                            "message": "正在基于完整字幕生成全面摘要...",
                        })
                        for sevt, sdata in stream_summarize(cdata["text"], info.title):
                            if sevt == "error":
                                yield ("done", {})
                                return
                            if sevt == "result":
                                sdata["is_partial"] = False
                                result_data = sdata
                            yield (sevt, sdata)

                inc_summarize_usage()
            else:
                yield ("progress", {"stage": "summary_generating", "message": "正在生成 AI 摘要..."})
                result_data = {}
                for event_type, data in stream_summarize(subtitle_text, info.title):
                    if event_type == "error":
                        yield ("done", {})
                        return
                    if event_type == "result":
                        result_data = data
                    yield (event_type, data)

                inc_summarize_usage()
                subtitle_for_rest = subtitle_text

            # 2. 思维导图
            yield ("progress", {"stage": "mindmap_generating", "message": "正在构建思维导图..."})
            mindmap_md = ""
            try:
                mindmap_md = generate_mindmap(subtitle_for_rest, info.title)
                yield ("mindmap", {"markdown": mindmap_md})
            except Exception as e:
                yield ("warn", {"message": f"思维导图生成失败: {str(e)}"})

            # 3. 学习笔记（流式）
            yield ("progress", {"stage": "notes_generating", "message": "正在生成学习笔记..."})
            notes_full = ""
            try:
                for event_type, data in stream_generate_notes(subtitle_for_rest, info.title):
                    yield (event_type, data)
                    if event_type == "notes_text":
                        notes_full += data.get("text", "")
            except Exception as e:
                yield ("warn", {"message": f"笔记生成失败: {str(e)}"})

            # 为笔记 section 注入字幕时间点
            if notes_full:
                sub_segments = None
                try:
                    from database import get_subtitle_from_db as _get_sub
                    _sub = _get_sub(canonical_url)
                    if _sub:
                        sub_segments = _sub.get("segments")
                except Exception:
                    pass
                notes_full = inject_notes_timestamps(notes_full, subtitle_text, segments=sub_segments)

            # ── 持久化 ──
            save_cache_json = json.dumps({
                "result": result_data,
                "mindmap_markdown": mindmap_md,
                "notes": notes_full,
            }, ensure_ascii=False)
            platform_name = detect_platform(canonical_url, info.extractor or "")
            save_cache(canonical_url, info.title, subtitle_text, sub_source, save_cache_json, fingerprint=fp, part_info=_build_part_info(canonical_url, info=info), platform=platform_name)

            # ── 标签提取（后台执行，不阻塞 SSE） ──
            try:
                summary_text = result_data.get("summary", "")
                tags = extract_tags(info.title, summary_text, canonical_url)
                if tags:
                    from core.cache import save_tags
                    save_tags(canonical_url, tags)
            except Exception:
                pass  # 标签提取失败不影响主流程

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
