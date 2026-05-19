"""字幕文本提取端点 — 返回清洗后的字幕/弹幕文本用于前端展示。"""

import asyncio

from fastapi import APIRouter, HTTPException, Query
import re as _re
from core.summarizer import clean_subtitle_text, _clean_danmaku_xml, extract_bilibili_subtitle, extract_bilibili_subtitle_by_cid, extract_subtitle_segments
from core.cache import get_video_info_cache, save_video_info_cache, video_fingerprint
from config import WHISPER_MAX_DURATION
from database import get_subtitle_from_db, save_subtitle_to_db

from api.routes import extract_url, downloader
from core.pipeline.subtitle import (
    _select_subtitle_lang, _download_subtitle_content,
    extract_bvid, _build_part_info, transcribe_and_correct,
)
from core.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


def _build_response(text, lang, name, ext, is_auto, segments=None):
    return {
        "text": text,
        "lang": lang,
        "name": name,
        "ext": ext,
        "is_auto": is_auto,
        "line_count": len(text.split('\n')),
        "segments": segments or [],
    }


@router.get("/api/subtitle/text")
async def get_subtitle_text(
    url: str = Query(..., description="视频 URL"),
    lang: str = Query("", description="首选语言"),
):
    """返回清洗后的字幕纯文本，用于前端展示和问答上下文。
    优先 DB 缓存 → Bilibili CC 字幕 → yt-dlp 原生字幕 → Whisper 转录。"""
    try:
        url = extract_url(url)

        # 0. DB 缓存检查
        cached_sub = get_subtitle_from_db(url)
        if cached_sub and len(cached_sub["full_text"].strip()) >= 20:
            # B站CC字幕需要有 [MM:SS] 时间戳，旧缓存可能没有，需重新获取
            if cached_sub["source"] == "bilibili_cc" and not _re.search(r'\[\d{2}:\d{2}\]', cached_sub["full_text"]):
                pass  # 跳过缓存，重新获取
            else:
                return _build_response(
                    cached_sub["full_text"], cached_sub["language"],
                    f"{cached_sub['language']}（{cached_sub['source']}，缓存）",
                    "txt", True,
                    cached_sub.get("segments"),
                )

        # 1. 优先尝试 Bilibili CC 字幕 API（多P视频按 cid 获取对应分P字幕）
        bilibili_sub = None
        if 'bilibili' in url.lower():
            p_match = _re.search(r'[?&]p=(\d+)', url)
            if p_match:
                bvid = extract_bvid(url)
                if bvid:
                    try:
                        from api.routes import downloader as _dl
                        info = _dl.parse_info(url)
                        parts = getattr(info, 'parts', []) or []
                        p_index = int(p_match.group(1))
                        part = next((p for p in parts if p.index == p_index), None)
                        if part and part.cid:
                            bilibili_sub = extract_bilibili_subtitle_by_cid(bvid, part.cid)
                    except Exception:
                        pass  # 下载器解析失败，降级到直接提取字幕
            if not bilibili_sub and not p_match:
                bilibili_sub = extract_bilibili_subtitle(url)
            elif bilibili_sub and bilibili_sub.get('has_subtitle') and len(bilibili_sub.get('text', '').strip()) < 100:
                # 分P字幕内容过短，视为无效，不降级到P1
                bilibili_sub = None
        if bilibili_sub and bilibili_sub['has_subtitle']:
            text = bilibili_sub['text']
            sub_lang = bilibili_sub['language']
            _pi = _build_part_info(url)
            save_subtitle_to_db(url, "bilibili_cc", sub_lang, bilibili_sub['text'], part_info=_pi, segments=bilibili_sub.get('segments', []))
            return _build_response(
                text, sub_lang,
                f"{sub_lang}（{'自动生成' if bilibili_sub['subtitle_type'] == 'auto' else '人工字幕'}）",
                "json", bilibili_sub['subtitle_type'] == 'auto',
                bilibili_sub.get('segments', []),
            )

        # 2. 降级：通过 yt-dlp 获取字幕
        cached_info = get_video_info_cache(url)
        if cached_info and cached_info.get("duration", 0) > WHISPER_MAX_DURATION:
            raise HTTPException(status_code=400, detail=f"视频时长 {int(cached_info['duration'])} 秒超过 {WHISPER_MAX_DURATION} 秒限制，不支持语音识别。请尝试有字幕的视频")

        info = downloader.parse_info(url)
        fp = video_fingerprint(info.extractor, info.id) if info.extractor and info.id else None
        canonical_url = info.webpage_url or url
        save_video_info_cache(canonical_url, info, fingerprint=fp)
        platform = info.extractor or ""
        sub_error = None

        if info.subtitles:
            selected = _select_subtitle_lang(info.subtitles, lang if lang else None)
            if selected:
                try:
                    raw_content, ext = await asyncio.get_event_loop().run_in_executor(
                        None, _download_subtitle_content, url, selected.lang, selected.is_auto
                    )
                    if ext == 'xml' or selected.lang == 'danmaku':
                        clean_text = _clean_danmaku_xml(raw_content)
                        segments = []
                    else:
                        clean_text = clean_subtitle_text(raw_content, ext)
                        segments = extract_subtitle_segments(raw_content, ext)

                    if len(clean_text.strip()) >= 20:
                        source = "youtube_auto" if selected.is_auto else "ytdlp_native"
                        _pi = _build_part_info(url, info)
                        save_subtitle_to_db(canonical_url, source, selected.lang, clean_text, info.title, platform, part_info=_pi, segments=segments)
                        return _build_response(clean_text, selected.lang, selected.name, ext, selected.is_auto, segments)
                except Exception as e:
                    sub_error = str(e)

        # 3. 兜底：Whisper 转录
        if info.duration and info.duration > WHISPER_MAX_DURATION:
            raise HTTPException(status_code=400, detail=f"视频时长 {int(info.duration)} 秒超过 {WHISPER_MAX_DURATION} 秒限制，不支持语音识别。请尝试有字幕的视频")

        corrected, raw_text = await transcribe_and_correct(
            url, lang, fp, info.title or "", info.description or ""
        )
        if corrected and len(corrected.strip()) >= 20:
            _pi = _build_part_info(url, info)
            save_subtitle_to_db(canonical_url, "whisper", lang or "auto", corrected, info.title, platform, part_info=_pi)
            return _build_response(corrected, lang or "auto", f"Whisper 语音识别（{lang or 'auto'}）", "txt", True)
        elif sub_error:
            raise HTTPException(status_code=404, detail=f"字幕获取失败: {sub_error}; Whisper 转录也失败")

        raise HTTPException(status_code=404, detail="该视频没有可用字幕，Whisper 转录也未成功")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"字幕文本提取失败: {str(e)}")
