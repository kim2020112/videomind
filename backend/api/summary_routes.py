"""AI 总结功能的路由（独立文件，不修改已有 routes.py）。

复用 routes.py 中的 extract_url、_download_subtitle_content、downloader 实例。
"""

import asyncio
import re

from fastapi import APIRouter, HTTPException, Request

from core.summary_models import SummarizeRequest, SummaryResult, ChapterItem, MindMapNode
from core.summarizer import clean_subtitle_text, summarize_subtitle, summarize_from_description, extract_bilibili_subtitle, extract_bilibili_subtitle_by_cid
from core.whisper import transcribe_video, is_model_available
from core.cache import get_whisper_cache, save_whisper_cache, get_video_info_cache, save_video_info_cache, video_fingerprint
from core.ai_client import correct_subtitle
from config import SUBTITLE_CORRECTION_ENABLED, WHISPER_MAX_DURATION

# 复用已有模块中的工具函数和实例
from api.routes import extract_url, _download_subtitle_content, downloader
from api.auth_routes import get_identity
from core.auth import check_usage_limit, log_usage

router = APIRouter()


def _select_subtitle_lang(subtitles, preferred: str = None):
    """选择最佳字幕语言。优先中文，其次英文，最后取第一个。"""
    if preferred:
        for sub in subtitles:
            if sub.lang == preferred or sub.lang.startswith(preferred):
                return sub
    for sub in subtitles:
        if sub.lang.startswith('zh') or sub.lang.startswith('zh-Hans'):
            return sub
    for sub in subtitles:
        if sub.lang.startswith('en'):
            return sub
    return subtitles[0] if subtitles else None


@router.post("/api/summarize", response_model=SummaryResult)
async def summarize_video(req: SummarizeRequest, request: Request):
    """AI 视频总结：提取字幕 -> DeepSeek 生成摘要/章节/思维导图。"""
    identity = get_identity(request)
    allowed, used, limit = check_usage_limit(
        identity.get("user_id"), identity.get("guest_id"), identity.get("guest_sig")
    )
    if not allowed:
        raise HTTPException(status_code=429, detail=f"今日 AI 次数已用完（{used}/{limit}）")

    try:
        url = extract_url(req.url)

        # 视频信息缓存预检：已缓存的超长视频直接跳过
        cached_info = get_video_info_cache(url)
        if cached_info and cached_info.get("duration", 0) > WHISPER_MAX_DURATION:
            # B站视频可能有 CC 字幕，先尝试获取
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
                _is_bili = 'bilibili' in url.lower()
                _no_cc_msg = "该B站视频没有CC字幕，" if _is_bili else ""
                if not desc or len(desc.strip()) < 20:
                    raise HTTPException(status_code=400, detail=f"{_no_cc_msg}视频时长 {int(cached_info['duration'])} 秒超过 {WHISPER_MAX_DURATION} 秒限制，不支持语音识别。该视频也没有简介，无法生成 AI 总结")
                result = await asyncio.get_event_loop().run_in_executor(
                    None, summarize_from_description, title, desc
                )
                log_usage(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
                          action="summary", status="SUCCESS")
                return SummaryResult(
                    summary=f"⚠️ {_no_cc_msg}视频时长 {int(cached_info['duration'])} 秒超过 {WHISPER_MAX_DURATION} 秒限制，以下总结基于视频简介生成，仅供参考。\n\n" + result.get("summary", ""),
                    chapters=[ChapterItem(**ch) for ch in result.get("chapters", [])],
                    mindmap=MindMapNode(title=title[:20], children=[]),
                )

        info = downloader.parse_info(url)
        fp = video_fingerprint(info.extractor, info.id) if info.extractor and info.id else None
        canonical_url = info.webpage_url or url
        save_video_info_cache(canonical_url, info, fingerprint=fp)

        # 无字幕时降级：Whisper 转录 > 视频简介
        whisper_text = None
        if not info.subtitles and is_model_available() and not (info.duration and info.duration > WHISPER_MAX_DURATION):
            whisper_text = get_whisper_cache(canonical_url, fingerprint=fp)
            if not whisper_text or len(whisper_text.strip()) < 50:
                try:
                    whisper_text = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None, transcribe_video, url, req.lang
                        ),
                        timeout=600,
                    )
                    if whisper_text and len(whisper_text.strip()) >= 50:
                        raw_text = whisper_text
                        if SUBTITLE_CORRECTION_ENABLED:
                            try:
                                whisper_text = await asyncio.wait_for(
                                    asyncio.get_event_loop().run_in_executor(
                                        None, correct_subtitle, whisper_text, info.title, info.description
                                    ),
                                    timeout=60,
                                )
                            except (asyncio.TimeoutError, Exception) as e:
                                print(f"[SubtitleCorrection] 校正失败，使用原始文本: {e}")
                        save_whisper_cache(canonical_url, whisper_text, req.lang or "auto", raw_text, fingerprint=fp)
                except (asyncio.TimeoutError, Exception):
                    whisper_text = None

            if whisper_text and len(whisper_text.strip()) >= 50:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, summarize_subtitle, whisper_text, info.title
                )
                log_usage(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
                          action="summary", status="SUCCESS")
                return SummaryResult(
                    summary="⚠️ 该视频无原生字幕，以下总结基于 Whisper 语音识别结果生成。\n\n" + result.get("summary", ""),
                    chapters=[ChapterItem(**ch) for ch in result.get("chapters", [])],
                    mindmap=MindMapNode(title=info.title[:20], children=[]),
                )

            if not info.description or len(info.description.strip()) < 20:
                raise HTTPException(status_code=400, detail="该视频没有字幕也没有简介，无法生成 AI 总结")
            result = await asyncio.get_event_loop().run_in_executor(
                None, summarize_from_description, info.title, info.description
            )
            log_usage(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
                      action="summary", status="SUCCESS")
            chapters = [ChapterItem(**ch) for ch in result.get("chapters", [])]
            mindmap = MindMapNode(title=info.title[:20], children=[])
            return SummaryResult(
                summary="⚠️ 该视频无字幕，以下总结基于视频简介生成，仅供参考。\n\n" + result.get("summary", ""),
                chapters=chapters,
                mindmap=mindmap,
            )

        selected = _select_subtitle_lang(info.subtitles, req.lang)
        if not selected:
            raise HTTPException(status_code=400, detail="未找到合适的字幕轨道")

        raw_content, ext = await asyncio.get_event_loop().run_in_executor(
            None, _download_subtitle_content, url, selected.lang, selected.is_auto
        )

        clean_text = clean_subtitle_text(raw_content, ext)
        if len(clean_text.strip()) < 50:
            # 字幕内容无效（如弹幕），先尝试 Whisper 转录
            whisper_text = None
            if is_model_available() and not (info.duration and info.duration > WHISPER_MAX_DURATION):
                whisper_text = get_whisper_cache(canonical_url, fingerprint=fp)
                if not whisper_text or len(whisper_text.strip()) < 50:
                    try:
                        whisper_text = await asyncio.wait_for(
                            asyncio.get_event_loop().run_in_executor(
                                None, transcribe_video, url, req.lang
                            ),
                            timeout=600,
                        )
                        if whisper_text and len(whisper_text.strip()) >= 50:
                            raw_text = whisper_text
                            if SUBTITLE_CORRECTION_ENABLED:
                                try:
                                    whisper_text = await asyncio.wait_for(
                                        asyncio.get_event_loop().run_in_executor(
                                            None, correct_subtitle, whisper_text, info.title, info.description
                                        ),
                                        timeout=60,
                                    )
                                except (asyncio.TimeoutError, Exception) as e:
                                    print(f"[SubtitleCorrection] 校正失败，使用原始文本: {e}")
                            save_whisper_cache(canonical_url, whisper_text, req.lang or "auto", raw_text, fingerprint=fp)
                    except (asyncio.TimeoutError, Exception):
                        whisper_text = None

            if whisper_text and len(whisper_text.strip()) >= 50:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, summarize_subtitle, whisper_text, info.title
                )
                log_usage(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
                          action="summary", status="SUCCESS")
                return SummaryResult(
                    summary="⚠️ 该视频原生字幕不可用，以下总结基于 Whisper 语音识别结果生成。\n\n" + result.get("summary", ""),
                    chapters=[ChapterItem(**ch) for ch in result.get("chapters", [])],
                    mindmap=MindMapNode(title=info.title[:20], children=[]),
                )

            # Whisper 不可用，降级到描述总结
            if info.description and len(info.description.strip()) >= 20:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, summarize_from_description, info.title, info.description
                )
                log_usage(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
                          action="summary", status="SUCCESS")
                chapters = [ChapterItem(**ch) for ch in result.get("chapters", [])]
                mindmap = MindMapNode(title=info.title[:20], children=[])
                return SummaryResult(
                    summary="⚠️ 该视频字幕内容不可用（可能为弹幕格式），以下总结基于视频简介生成，仅供参考。\n\n" + result.get("summary", ""),
                    chapters=chapters,
                    mindmap=mindmap,
                )
            raise HTTPException(status_code=400, detail="字幕内容过短，无法生成有效总结")

        result = await asyncio.get_event_loop().run_in_executor(
            None, summarize_subtitle, clean_text, info.title
        )

        log_usage(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
                  action="summary", status="SUCCESS")

        chapters = [ChapterItem(**ch) for ch in result.get("chapters", [])]
        mindmap = MindMapNode(title="视频内容", children=[])

        return SummaryResult(
            summary=result.get("summary", ""),
            chapters=chapters,
            mindmap=mindmap,
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 总结失败: {str(e)}")
