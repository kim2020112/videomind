"""统一字幕获取入口 — 三级降级策略（原生字幕 > yt-dlp > Whisper预留）。"""

import asyncio
import re
from dataclasses import dataclass
from typing import Optional

from core.summarizer import (
    extract_bilibili_subtitle,
    clean_subtitle_text,
    _clean_danmaku_xml,
)


@dataclass
class SubtitleResult:
    source: str  # bilibili_cc / ytdlp / whisper
    language: str
    full_text: str
    segments: list  # [{start, end, text}]
    is_auto: bool = False


def _detect_platform(url: str) -> Optional[str]:
    if "bilibili.com" in url or "b23.tv" in url:
        return "bilibili"
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    if "douyin.com" in url:
        return "douyin"
    if "xiaohongshu.com" in url:
        return "xiaohongshu"
    if "tiktok.com" in url:
        return "tiktok"
    return None


async def acquire_subtitle(
    url: str,
    preferred_lang: str = "",
    downloader=None,
) -> Optional[SubtitleResult]:
    """
    统一字幕获取，按优先级尝试：
    1. 平台原生字幕（B站CC字幕API）
    2. yt-dlp 字幕下载
    3. Whisper 转录（预留，暂未实现）
    """
    # Level 1: 平台原生字幕
    result = await _try_platform_subtitle(url)
    if result:
        return result

    # Level 2: yt-dlp 字幕
    if downloader:
        result = await _try_ytdlp_subtitle(url, preferred_lang, downloader)
        if result:
            return result

    # Level 3: Whisper（预留接口）
    # result = await _try_whisper(url)
    # if result:
    #     return result

    return None


async def _try_platform_subtitle(url: str) -> Optional[SubtitleResult]:
    platform = _detect_platform(url)
    if platform == "bilibili":
        data = await asyncio.get_event_loop().run_in_executor(
            None, extract_bilibili_subtitle, url
        )
        if data and data.get("has_subtitle"):
            return SubtitleResult(
                source="bilibili_cc",
                language=data["language"],
                full_text=data["full_text"],
                segments=data.get("segments", []),
                is_auto=data.get("subtitle_type") == "auto",
            )
    return None


async def _try_ytdlp_subtitle(
    url: str, preferred_lang: str, downloader
) -> Optional[SubtitleResult]:
    from core.pipeline.subtitle import _download_subtitle_content, _select_subtitle_lang

    info = await asyncio.get_event_loop().run_in_executor(
        None, downloader.parse_info, url
    )
    if not info.subtitles:
        return None

    selected = _select_subtitle_lang(info.subtitles, preferred_lang or None)
    if not selected:
        return None

    raw_content, ext = await asyncio.get_event_loop().run_in_executor(
        None, _download_subtitle_content, url, selected.lang, selected.is_auto
    )

    if ext == "xml" or selected.lang == "danmaku":
        text = _clean_danmaku_xml(raw_content)
    else:
        text = clean_subtitle_text(raw_content, ext)

    if len(text.strip()) < 20:
        return None

    return SubtitleResult(
        source="ytdlp",
        language=selected.lang,
        full_text=text,
        segments=[],
        is_auto=selected.is_auto,
    )
