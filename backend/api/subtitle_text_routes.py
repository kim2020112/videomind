"""字幕文本提取端点 — 返回清洗后的字幕/弹幕文本用于前端展示。"""

import asyncio

from fastapi import APIRouter, HTTPException, Query
from core.summarizer import clean_subtitle_text, _clean_danmaku_xml, extract_bilibili_subtitle
from core.whisper import transcribe_video, is_model_available
from core.cache import get_whisper_cache, save_whisper_cache, get_video_info_cache, save_video_info_cache
from core.ai_client import correct_subtitle
from config import SUBTITLE_CORRECTION_ENABLED, WHISPER_MAX_DURATION

from api.routes import extract_url, _download_subtitle_content, downloader
from api.summary_routes import _select_subtitle_lang

router = APIRouter()


@router.get("/api/subtitle/text")
async def get_subtitle_text(
    url: str = Query(..., description="视频 URL"),
    lang: str = Query("", description="首选语言"),
):
    """返回清洗后的字幕纯文本，用于前端展示和问答上下文。
    优先 Bilibili CC 字幕 → yt-dlp 原生字幕 → Whisper 转录。"""
    try:
        url = extract_url(url)

        # 1. 优先尝试 Bilibili CC 字幕 API
        bilibili_sub = extract_bilibili_subtitle(url)
        if bilibili_sub and bilibili_sub['has_subtitle']:
            return {
                "text": bilibili_sub['text'],
                "lang": bilibili_sub['language'],
                "name": f"{bilibili_sub['language']}（{'自动生成' if bilibili_sub['subtitle_type'] == 'auto' else '人工字幕'}）",
                "ext": "json",
                "is_auto": bilibili_sub['subtitle_type'] == 'auto',
                "line_count": len(bilibili_sub['text'].split('\n')),
                "segments": bilibili_sub.get('segments', []),
            }

        # 2. 降级：通过 yt-dlp 获取字幕
        # 视频信息缓存预检：已缓存的超长视频直接跳过
        cached_info = get_video_info_cache(url)
        if cached_info and cached_info.get("duration", 0) > WHISPER_MAX_DURATION:
            raise HTTPException(status_code=400, detail=f"视频时长 {int(cached_info['duration'])} 秒超过 {WHISPER_MAX_DURATION} 秒限制，不支持语音识别。请尝试有字幕的视频")

        info = downloader.parse_info(url)
        save_video_info_cache(url, info)
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
                    else:
                        clean_text = clean_subtitle_text(raw_content, ext)

                    if len(clean_text.strip()) >= 20:
                        return {
                            "text": clean_text,
                            "lang": selected.lang,
                            "name": selected.name,
                            "ext": ext,
                            "is_auto": selected.is_auto,
                            "line_count": len(clean_text.split('\n')),
                            "segments": [],
                        }
                except Exception as e:
                    sub_error = str(e)

        # 3. 兜底：Whisper 转录
        if is_model_available():
            if info.duration and info.duration > WHISPER_MAX_DURATION:
                raise HTTPException(status_code=400, detail=f"视频时长 {int(info.duration)} 秒超过 {WHISPER_MAX_DURATION} 秒限制，不支持语音识别。请尝试有字幕的视频")

            cached_whisper = get_whisper_cache(url)
            if cached_whisper and len(cached_whisper.strip()) >= 20:
                return {
                    "text": cached_whisper,
                    "lang": lang or "auto",
                    "name": f"Whisper 语音识别（{lang or 'auto'}，缓存）",
                    "ext": "txt",
                    "is_auto": True,
                    "line_count": len(cached_whisper.split('\n')),
                    "segments": [],
                }

            try:
                whisper_text = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, transcribe_video, url, lang if lang else None
                    ),
                    timeout=600,
                )
                if whisper_text and len(whisper_text.strip()) >= 20:
                    # AI 校正 Whisper 转录文本
                    corrected = whisper_text
                    if SUBTITLE_CORRECTION_ENABLED:
                        try:
                            corrected = await asyncio.wait_for(
                                asyncio.get_event_loop().run_in_executor(
                                    None, correct_subtitle, whisper_text, info.title or "", info.description or ""
                                ),
                                timeout=60,
                            )
                        except (asyncio.TimeoutError, Exception) as e:
                            print(f"[SubtitleCorrection] 校正失败，使用原始文本: {e}")
                            corrected = whisper_text
                    save_whisper_cache(url, corrected, lang or "auto", whisper_text)
                    return {
                        "text": corrected,
                        "lang": lang or "auto",
                        "name": f"Whisper 语音识别（{lang or 'auto'}）",
                        "ext": "txt",
                        "is_auto": True,
                        "line_count": len(whisper_text.split('\n')),
                        "segments": [],
                    }
            except asyncio.TimeoutError:
                if sub_error:
                    raise HTTPException(status_code=404, detail=f"字幕获取失败: {sub_error}; Whisper 转录超时")
            except Exception as e:
                if sub_error:
                    raise HTTPException(status_code=404, detail=f"字幕获取失败: {sub_error}; Whisper 转录也失败: {str(e)}")

        raise HTTPException(status_code=404, detail="该视频没有可用字幕，Whisper 转录也未成功")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"字幕文本提取失败: {str(e)}")
