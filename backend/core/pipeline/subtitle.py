"""字幕获取 Pipeline。

四级降级：DB 缓存 → B站 CC → yt-dlp 原生 → Whisper 转录（不含 AI 校正）。

同时提供字幕相关共享工具函数，供 api/ 层导入。
"""

import asyncio
import glob as _glob
import os
import re
import shutil as _shutil
import tempfile as _tempfile

from database import get_subtitle_from_db, save_subtitle_to_db
from core.summarizer import (
    clean_subtitle_text, _clean_danmaku_xml,
    extract_bilibili_subtitle, extract_bilibili_subtitle_by_cid,
)
from core.cache import get_whisper_cache, save_whisper_cache, get_video_info_cache
from core.whisper import transcribe_video_async, is_model_available
from core.ai_client import correct_subtitle
from config import WHISPER_MAX_DURATION, SUBTITLE_CORRECTION_ENABLED
from core.logging_config import get_logger

logger = get_logger(__name__)

# ─── 共享工具函数 ───────────────────────────────────────────

def extract_bvid(url: str) -> str | None:
    """从 URL 中提取 Bilibili BV 号。"""
    m = re.search(r'(BV\w+)', url)
    return m.group(1) if m else None


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


def _download_subtitle_content(url: str, lang: str, is_auto: bool) -> tuple[str, str]:
    """用 yt-dlp 下载字幕文件，返回 (文件内容, 文件扩展名)。"""
    import yt_dlp

    tmpdir = _tempfile.mkdtemp(prefix='subtitle_')
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': [lang],
        'subtitlesformat': 'srt/vtt/json3/best',
        'outtmpl': os.path.join(tmpdir, '%(id)s'),
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)

        candidates = _glob.glob(os.path.join(tmpdir, '*'))
        sub_files = [f for f in candidates if os.path.isfile(f)
                     and os.path.splitext(f)[1].lower() in ('.srt', '.vtt', '.json3', '.srv1', '.srv2', '.srv3')]
        if not sub_files:
            sub_files = [f for f in candidates if os.path.isfile(f) and not f.endswith('.part')]
        if not sub_files:
            raise Exception('字幕下载失败，可能该视频没有此语言的字幕')

        sub_file = sub_files[0]
        ext = os.path.splitext(sub_file)[1].lstrip('.')
        with open(sub_file, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        return content, ext
    finally:
        _shutil.rmtree(tmpdir, ignore_errors=True)


def _build_part_info(url: str, info=None, parts: list = None) -> str:
    """构建分P信息字符串。兼容 dict 和对象类型。"""
    def _get(obj, attr):
        if isinstance(obj, dict):
            return obj.get(attr)
        return getattr(obj, attr, None)

    p_match = re.search(r'[?&]p=(\d+)', url)
    if not p_match:
        # 基础 URL 隐含 P1
        if info and hasattr(info, 'parts') and info.parts:
            part = next((p for p in info.parts if _get(p, 'index') == 1), None)
            if part:
                return _get(part, 'title') or "P1"
        return ""
    p_index = int(p_match.group(1))
    if info and hasattr(info, 'parts') and info.parts:
        part = next((p for p in info.parts if _get(p, 'index') == p_index), None)
        if part:
            return _get(part, 'title') or f"P{p_index}"
    if parts:
        part = next((p for p in parts if _get(p, 'index') == p_index), None)
        if part:
            return _get(part, 'title') or f"P{p_index}"
    return f"P{p_index}"


def try_get_bilibili_cc_subtitle(url: str, cached_info: dict = None) -> dict | None:
    """尝试获取 B站 CC 字幕（支持多P分P cid 精确获取）。
    返回字幕 dict（has_subtitle, text, language 等）或 None。
    多P视频指定分P无CC字幕时返回 None，不降级到P1。
    """
    if 'bilibili' not in url.lower():
        return None

    p_match = re.search(r'[?&]p=(\d+)', url)
    if p_match and cached_info:
        parts = cached_info.get('parts', []) or []
        p_idx = int(p_match.group(1))
        part = next((p for p in parts if p.get('index') == p_idx), None)
        if part and part.get('cid'):
            bvid = extract_bvid(url)
            if bvid:
                return extract_bilibili_subtitle_by_cid(bvid, part['cid'])
        # 多P指定分P无法获取CC字幕，返回 None（不降级到P1）
        return None

    return extract_bilibili_subtitle(url)


async def transcribe_and_correct(url: str, lang: str = None, fingerprint: str = None,
                                  title: str = "", description: str = "") -> tuple[str | None, str | None]:
    """Whisper 转录 + AI 校正（含缓存）。返回 (corrected_text, raw_text)，失败返回 (None, None)。"""
    cached = get_whisper_cache(url, fingerprint=fingerprint)
    if cached and len(cached.strip()) >= 20:
        logger.info(f"Whisper缓存命中")
        return cached, cached

    if not is_model_available():
        return None, None

    try:
        logger.info(f"开始 Whisper 转录...")
        raw_text = await asyncio.wait_for(
            transcribe_video_async(url, lang),
            timeout=600,
        )
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"Whisper 转录失败: {e}")
        return None, None

    if not raw_text or len(raw_text.strip()) < 20:
        return None, None

    corrected = raw_text
    if SUBTITLE_CORRECTION_ENABLED:
        try:
            corrected = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, correct_subtitle, raw_text, title, description
                ),
                timeout=60,
            )
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning(f"字幕校正失败，使用原始文本: {e}")
            corrected = raw_text

    save_whisper_cache(url, corrected, lang or "auto", raw_text, fingerprint=fingerprint)
    logger.info(f"Whisper 转录完成 len={len(corrected)}")
    return corrected, raw_text


# ─── Pipeline ────────────────────────────────────────────────

async def fetch_subtitle(url: str, info, lang: str = None, fingerprint: str = None,
                         trace_id: str = "") -> tuple[str, str, str]:
    """标准化字幕获取（DB 优先，减少重复 API 调用）。

    返回 (subtitle_text, source, language)。不含 AI 校正。
    """
    platform = info.extractor or ""

    # ── DB 缓存检查 ──
    cached_sub = get_subtitle_from_db(url)
    if cached_sub and len(cached_sub["full_text"].strip()) >= 50:
        if cached_sub["source"] == "bilibili_cc" and not re.search(r'\[\d{2}:\d{2}\]', cached_sub["full_text"]):
            logger.info(f"DB缓存的B站CC字幕缺少时间戳，跳过缓存重新获取")
        else:
            logger.info(f"字幕命中DB缓存 source={cached_sub['source']}")
            return cached_sub["full_text"], cached_sub["source"], cached_sub["language"]

    # ── Pipeline 1: Bilibili CC 字幕 API ──
    bilibili_sub = None
    if 'bilibili' in (info.extractor or '').lower():
        p_match = re.search(r'[?&]p=(\d+)', url)
        parts = getattr(info, 'parts', []) or []
        if p_match and len(parts) > 1:
            p_index = int(p_match.group(1))
            part = next((p for p in parts if p.index == p_index), None)
            if part and part.cid:
                bvid = extract_bvid(url)
                if bvid:
                    logger.info(f"尝试B站分P字幕 bvid={bvid} cid={part.cid}")
                    bilibili_sub = extract_bilibili_subtitle_by_cid(bvid, part.cid)
            # 分P无独立CC字幕时，不降级到P1（内容不同），继续后续管线
            if bilibili_sub and bilibili_sub.get('has_subtitle') and len(bilibili_sub.get('text', '').strip()) < 100:
                logger.info(f"分P字幕内容过短(len={len(bilibili_sub.get('text',''))}), 视为无效")
                bilibili_sub = None
            elif not bilibili_sub:
                logger.info(f"分P无CC字幕，继续后续管线")
        else:
            bvid = extract_bvid(url)
            logger.info(f"尝试B站CC字幕 bvid={bvid or 'N/A'}")
            bilibili_sub = extract_bilibili_subtitle(url)
        if bilibili_sub:
            logger.info(f"B站CC字幕获取成功 has_subtitle={bilibili_sub.get('has_subtitle')} lang={bilibili_sub.get('language')}")
        else:
            logger.info(f"B站CC字幕获取失败（返回 None），尝试下一降级")
    if bilibili_sub and bilibili_sub['has_subtitle']:
        text = bilibili_sub['text']
        sub_lang = bilibili_sub.get('language', 'zh')
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
                    logger.info(f"yt-dlp字幕获取成功 source={source}")
                    return subtitle_text, source, selected.lang
            except Exception as e:
                logger.info(f"yt-dlp字幕获取失败: {e}")

    # ── Pipeline 3: Whisper 转录（兜底，不含 AI 校正） ──
    if is_model_available():
        if info.duration and info.duration > WHISPER_MAX_DURATION:
            logger.info(f"视频时长 {info.duration}s 超过限制 {WHISPER_MAX_DURATION}s，跳过 Whisper")
            return None, "", ""

        cached_whisper = get_whisper_cache(url, fingerprint=fingerprint)
        if cached_whisper and len(cached_whisper.strip()) >= 20:
            logger.info(f"Whisper缓存命中")
            return cached_whisper, "whisper", lang or "auto"

        try:
            logger.info(f"开始 Whisper 转录...")
            whisper_text = await asyncio.wait_for(
                transcribe_video_async(url, lang),
                timeout=600,
            )
            if whisper_text and len(whisper_text.strip()) >= 20:
                save_whisper_cache(url, whisper_text, lang or "auto", whisper_text, fingerprint=fingerprint)
                logger.info(f"Whisper 转录完成 len={len(whisper_text)}")
                return whisper_text, "whisper", lang or "auto"
        except asyncio.TimeoutError:
            logger.info(f"Whisper 转录超时")
        except Exception as e:
            logger.info(f"Whisper 转录失败: {e}")

    logger.info(f"所有字幕获取方式均失败")
    return None, "", ""


def save_subtitle(url: str, info, subtitle_text: str, source: str, lang: str):
    """将字幕持久化到 DB。"""
    platform = info.extractor or ""
    _pi = _build_part_info(url, info=info)
    save_subtitle_to_db(url, source, lang, subtitle_text, info.title, platform, part_info=_pi)
