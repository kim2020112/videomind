"""AI 总结功能的路由（独立文件，不修改已有 routes.py）。

复用 routes.py 中的 extract_url、downloader 实例。
"""

import asyncio
import re

from fastapi import APIRouter, HTTPException, Request

from core.summary_models import SummarizeRequest, SummaryResult, ChapterItem
from core.summarizer import clean_subtitle_text, summarize_subtitle, summarize_from_description
from core.cache import get_video_info_cache, save_video_info_cache, video_fingerprint
from config import WHISPER_MAX_DURATION
from core.pipeline.subtitle import (
    _select_subtitle_lang, _download_subtitle_content,
    try_get_bilibili_cc_subtitle, transcribe_and_correct,
)

# 复用已有模块中的工具函数和实例
from api.routes import extract_url, downloader
from api.auth_routes import get_identity
from core.logging_config import get_logger

logger = get_logger(__name__)
from core.auth import check_usage_limit, log_usage

router = APIRouter()


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
            bilibili_sub = try_get_bilibili_cc_subtitle(url, cached_info)
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
                )

        info = downloader.parse_info(url)
        fp = video_fingerprint(info.extractor, info.id) if info.extractor and info.id else None
        canonical_url = info.webpage_url or url
        save_video_info_cache(canonical_url, info, fingerprint=fp)

        # 无字幕时降级：Whisper 转录 > 视频简介
        whisper_text = None
        if not info.subtitles and not (info.duration and info.duration > WHISPER_MAX_DURATION):
            whisper_text, _ = await transcribe_and_correct(
                url, req.lang, fp, info.title, info.description
            )

            if whisper_text and len(whisper_text.strip()) >= 50:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, summarize_subtitle, whisper_text, info.title
                )
                log_usage(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
                          action="summary", status="SUCCESS")
                return SummaryResult(
                    summary="⚠️ 该视频无原生字幕，以下总结基于 Whisper 语音识别结果生成。\n\n" + result.get("summary", ""),
                    chapters=[ChapterItem(**ch) for ch in result.get("chapters", [])],
                )

            if not info.description or len(info.description.strip()) < 20:
                raise HTTPException(status_code=400, detail="该视频没有字幕也没有简介，无法生成 AI 总结")
            result = await asyncio.get_event_loop().run_in_executor(
                None, summarize_from_description, info.title, info.description
            )
            log_usage(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
                      action="summary", status="SUCCESS")
            chapters = [ChapterItem(**ch) for ch in result.get("chapters", [])]
            return SummaryResult(
                summary="⚠️ 该视频无字幕，以下总结基于视频简介生成，仅供参考。\n\n" + result.get("summary", ""),
                chapters=chapters,
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
            if not (info.duration and info.duration > WHISPER_MAX_DURATION):
                whisper_text, _ = await transcribe_and_correct(
                    url, req.lang, fp, info.title, info.description
                )

            if whisper_text and len(whisper_text.strip()) >= 50:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, summarize_subtitle, whisper_text, info.title
                )
                log_usage(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
                          action="summary", status="SUCCESS")
                return SummaryResult(
                    summary="⚠️ 该视频原生字幕不可用，以下总结基于 Whisper 语音识别结果生成。\n\n" + result.get("summary", ""),
                    chapters=[ChapterItem(**ch) for ch in result.get("chapters", [])],
                )

            # Whisper 不可用，降级到描述总结
            if info.description and len(info.description.strip()) >= 20:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, summarize_from_description, info.title, info.description
                )
                log_usage(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
                          action="summary", status="SUCCESS")
                chapters = [ChapterItem(**ch) for ch in result.get("chapters", [])]
                return SummaryResult(
                    summary="⚠️ 该视频字幕内容不可用（可能为弹幕格式），以下总结基于视频简介生成，仅供参考。\n\n" + result.get("summary", ""),
                    chapters=chapters,
                )
            raise HTTPException(status_code=400, detail="字幕内容过短，无法生成有效总结")

        result = await asyncio.get_event_loop().run_in_executor(
            None, summarize_subtitle, clean_text, info.title
        )

        log_usage(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
                  action="summary", status="SUCCESS")

        chapters = [ChapterItem(**ch) for ch in result.get("chapters", [])]

        return SummaryResult(
            summary=result.get("summary", ""),
            chapters=chapters,
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 总结失败: {str(e)}")
