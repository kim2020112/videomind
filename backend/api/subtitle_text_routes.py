"""字幕文本提取端点 — 返回清洗后的字幕/弹幕文本用于前端展示。"""

import asyncio

from fastapi import APIRouter, HTTPException, Query
from core.summarizer import clean_subtitle_text, _clean_danmaku_xml, extract_bilibili_subtitle

from api.routes import extract_url, _download_subtitle_content, downloader
from api.summary_routes import _select_subtitle_lang

router = APIRouter()


@router.get("/api/subtitle/text")
async def get_subtitle_text(
    url: str = Query(..., description="视频 URL"),
    lang: str = Query("", description="首选语言"),
):
    """返回清洗后的字幕纯文本，用于前端展示和问答上下文。
    优先使用 Bilibili CC 字幕 API，降级到 yt-dlp 字幕。"""
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
        info = downloader.parse_info(url)
        if not info.subtitles:
            raise HTTPException(status_code=404, detail="该视频没有可用的字幕轨道")

        selected = _select_subtitle_lang(info.subtitles, lang if lang else None)
        if not selected:
            raise HTTPException(status_code=404, detail="未找到合适的字幕轨道")

        raw_content, ext = await asyncio.get_event_loop().run_in_executor(
            None, _download_subtitle_content, url, selected.lang, selected.is_auto
        )

        # danmaku XML 用专用解析器，其他格式走通用清洗
        if ext == 'xml' or selected.lang == 'danmaku':
            clean_text = _clean_danmaku_xml(raw_content)
        else:
            clean_text = clean_subtitle_text(raw_content, ext)

        if len(clean_text.strip()) < 20:
            raise HTTPException(status_code=400, detail="字幕内容过短，可能是弹幕格式或其他非文本数据")

        return {
            "text": clean_text,
            "lang": selected.lang,
            "name": selected.name,
            "ext": ext,
            "is_auto": selected.is_auto,
            "line_count": len(clean_text.split('\n')),
            "segments": [],
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"字幕文本提取失败: {str(e)}")
