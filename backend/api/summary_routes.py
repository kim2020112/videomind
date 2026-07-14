"""AI 总结功能的路由（独立文件，不修改已有 routes.py）。

复用 routes.py 中的 extract_url、downloader 实例。
"""

import asyncio

from fastapi import APIRouter, HTTPException, Request

from core.summary_models import SummarizeRequest, SummaryResult, ChapterItem
from core.summarizer import summarize_subtitle, summarize_from_description
from core.cache import get_video_info_cache, video_fingerprint
from config import WHISPER_MAX_DURATION
from core.pipeline.subtitle import (
    BilibiliSubtitleUnavailable,
    try_get_bilibili_cc_subtitle,
    fetch_subtitle,
)

# 复用已有模块中的工具函数和实例
from api.routes import extract_url, downloader
from api.security import ensure_public_http_url, require_identity
from core.features import is_ai_available
from core.generation_commit import validate_summary_result
from core.logging_config import get_logger
from core.video import canonical_video_url, is_bilibili_video, video_duration_for_url

logger = get_logger(__name__)
from core.auth import check_usage_limit, log_usage

router = APIRouter()


@router.post("/api/summarize", response_model=SummaryResult)
async def summarize_video(req: SummarizeRequest, request: Request):
    """AI 视频总结：提取字幕 -> DeepSeek 生成摘要/章节/思维导图。"""
    if not is_ai_available():
        raise HTTPException(status_code=503, detail="feature_unavailable: AI 功能不可用（SDK 未安装、未启用或未配置 API Key）")
    identity = require_identity(request)
    allowed, used, limit = check_usage_limit(
        identity.get("user_id"), identity.get("guest_id"), identity.get("guest_sig")
    )
    if not allowed:
        raise HTTPException(status_code=429, detail=f"今日 AI 次数已用完（{used}/{limit}）")

    try:
        url = extract_url(req.url)
        ensure_public_http_url(url)

        # 视频信息缓存预检：已缓存的超长视频直接跳过
        cached_info = get_video_info_cache(url)
        cached_duration = video_duration_for_url(url, cached_info) if cached_info else 0
        if WHISPER_MAX_DURATION > 0 and cached_duration > WHISPER_MAX_DURATION:
            bilibili_sub = try_get_bilibili_cc_subtitle(url, cached_info)
            if bilibili_sub and bilibili_sub.get('has_subtitle'):
                pass  # 有 B站 CC 字幕，跳过快速路径，走正常 AI 管线
            else:
                desc = cached_info.get("description", "")
                title = cached_info.get("title", "")
                _is_bili = is_bilibili_video(url, cached_info)
                if _is_bili and bilibili_sub is None:
                    raise HTTPException(
                        status_code=503,
                        detail="B站字幕接口暂时不可用，请稍后重试；未生成简介总结，也未启动语音转录",
                    )
                _no_cc_msg = "该B站视频没有CC字幕，" if _is_bili else ""
                if not desc or len(desc.strip()) < 20:
                    raise HTTPException(status_code=400, detail=f"{_no_cc_msg}视频时长 {int(cached_duration)} 秒超过 {WHISPER_MAX_DURATION} 秒限制，不支持语音识别。该视频也没有简介，无法生成 AI 总结")
                result = await asyncio.get_event_loop().run_in_executor(
                    None, summarize_from_description, title, desc
                )
                validate_summary_result(result)
                response = SummaryResult(
                    summary=f"⚠️ {_no_cc_msg}视频时长 {int(cached_duration)} 秒超过 {WHISPER_MAX_DURATION} 秒限制，以下总结基于视频简介生成，仅供参考。\n\n" + result.get("summary", ""),
                    chapters=[ChapterItem(**ch) for ch in result.get("chapters", [])],
                )
                log_usage(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
                          action="summary", status="SUCCESS")
                return response

        info = downloader.parse_info(url)
        fp = video_fingerprint(info.extractor, info.id) if info.extractor and info.id else None
        canonical_url = canonical_video_url(url, info)
        info.webpage_url = canonical_url

        # 统一字幕获取管线（DB 缓存 → B站 CC → yt-dlp → Whisper）
        subtitle_text, sub_source, sub_lang = await fetch_subtitle(
            canonical_url, info, req.lang, fingerprint=fp, trace_id=""
        )

        if subtitle_text and len(subtitle_text.strip()) >= 50:
            result = await asyncio.get_event_loop().run_in_executor(
                None, summarize_subtitle, subtitle_text, info.title
            )
            validate_summary_result(result)
            response = SummaryResult(
                summary=result.get("summary", ""),
                chapters=[ChapterItem(**ch) for ch in result.get("chapters", [])],
            )
            log_usage(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
                      action="summary", status="SUCCESS")
            return response

        # 全部字幕获取方式失败，降级到视频简介总结
        if info.description and len(info.description.strip()) >= 20:
            result = await asyncio.get_event_loop().run_in_executor(
                None, summarize_from_description, info.title, info.description
            )
            validate_summary_result(result)
            response = SummaryResult(
                summary="⚠️ 该视频无可用字幕，以下总结基于视频简介生成，仅供参考。\n\n" + result.get("summary", ""),
                chapters=[ChapterItem(**ch) for ch in result.get("chapters", [])],
            )
            log_usage(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
                      action="summary", status="SUCCESS")
            return response

        raise HTTPException(status_code=400, detail="该视频没有字幕也没有简介，无法生成 AI 总结")

    except BilibiliSubtitleUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 总结失败: {str(e)}")
