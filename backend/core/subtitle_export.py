"""Exports use the same validated Bilibili subtitle service as the workspace."""
import asyncio
from core.video import is_bilibili_video
from core.pipeline.subtitle import fetch_subtitle, _download_subtitle_content


def download_subtitle_content(url, lang, is_auto, downloader):
    if not is_bilibili_video(url):
        return _download_subtitle_content(url, lang, is_auto)
    from core.video_metadata import learning_video_info
    from database import get_subtitle_from_db
    from core.subtitle_validation import validate_cached_subtitle
    info = learning_video_info(url, downloader)
    text, _, actual = asyncio.run(fetch_subtitle(url, info, lang, persist=True))
    if not text:
        raise ValueError('该视频没有可导出的平台字幕')
    normalize = lambda value: (value or '').lower().removeprefix('ai-').replace('zh-hans', 'zh').replace('zh-cn', 'zh')
    if lang and normalize(lang) != normalize(actual):
        raise ValueError('当前可用字幕语言与所选语言不同，请选择当前字幕语言后重试')
    sub = validate_cached_subtitle(url, get_subtitle_from_db(url), info)
    segments = (sub or {}).get('segments') or []
    if not segments:
        return text, 'txt'
    def stamp(value):
        ms = round(float(value) * 1000)
        return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'
    return '\n\n'.join(f"{i}\n{stamp(s['start'])} --> {stamp(s['end'])}\n{s['text']}" for i, s in enumerate(segments, 1)) + '\n', 'srt'
