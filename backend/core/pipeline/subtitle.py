"""字幕获取 Pipeline。

三级获取：DB 缓存 → B站 CC → yt-dlp 原生。

Whisper 由 SQLite 后台任务和短生命周期子进程处理，不在 Web 进程中运行。

同时提供字幕相关共享工具函数，供 api/ 层导入。
"""

import asyncio
import glob as _glob
import os
import re
import shutil as _shutil
import tempfile as _tempfile

from database import get_subtitle_from_db, save_subtitle_to_db
from core.bilibili_cache import refresh_responses
from core.video import video_duration_for_url
from core.summarizer import (
    clean_subtitle_text, _clean_danmaku_xml,
    extract_bilibili_subtitle, extract_bilibili_subtitle_by_cid, extract_subtitle_segments,
)
from core.cache import get_video_info_cache
from core.bilibili import youtube_dl, ydl_opts_for
from core.logging_config import get_logger
from core.bilibili_guard import BilibiliAccessBlocked
from core.video import canonical_video_url, is_bilibili_video

logger = get_logger(__name__)


class BilibiliSubtitleUnavailable(RuntimeError):
    """The platform could not confirm whether a Bilibili subtitle exists."""

# ─── 共享工具函数 ───────────────────────────────────────────

def extract_bvid(url: str) -> str | None:
    """从 URL 中提取 Bilibili BV 号。"""
    m = re.search(r'(BV\w+)', url)
    return m.group(1) if m else None


def _select_subtitle_lang(subtitles, preferred: str = None):
    """选择最佳字幕语言。优先中文，其次英文，最后取第一个。"""
    def normalize(language):
        value = (language or "").lower().replace("_", "-")
        return value[3:] if value.startswith("ai-") else value

    if preferred:
        wanted = normalize(preferred)
        for sub in subtitles:
            language = normalize(sub.lang)
            if language == wanted or language.startswith(wanted):
                return sub
    for sub in subtitles:
        if normalize(sub.lang).startswith("zh"):
            return sub
    for sub in subtitles:
        if normalize(sub.lang).startswith("en"):
            return sub
    return subtitles[0] if subtitles else None


def _is_english_language(language: str) -> bool:
    value = (language or "").lower().replace("_", "-")
    if value.startswith("ai-"):
        value = value[3:]
    return value == "en" or value.startswith("en-")


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
    ydl_opts.update(ydl_opts_for(url))

    try:
        with youtube_dl(ydl_opts, url) as ydl:
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


def try_get_bilibili_cc_subtitle(url: str, cached_info=None) -> dict | None:
    """尝试获取 B站 CC 字幕（支持多P分P cid 精确获取）。
    返回字幕 dict（has_subtitle, text, language 等）或 None。
    多P视频指定分P无CC字幕时返回 None，不降级到P1。
    """
    if cached_info is not None:
        url = canonical_video_url(url, cached_info)
    if not is_bilibili_video(url, cached_info):
        return None

    p_match = re.search(r'[?&]p=(\d+)', url)
    if cached_info:
        parts = (
            cached_info.get('parts', [])
            if isinstance(cached_info, dict)
            else getattr(cached_info, 'parts', [])
        ) or []
        p_idx = int(p_match.group(1)) if p_match else 1
        part = next((p for p in parts if (
            p.get('index') if isinstance(p, dict) else getattr(p, 'index', None)
        ) == p_idx), None)
        cid = part.get('cid') if isinstance(part, dict) else getattr(part, 'cid', None)
        if cid:
            bvid = extract_bvid(url)
            if bvid:
                return extract_bilibili_subtitle_by_cid(bvid, cid)
        # Unknown explicit parts must never silently fall back to P1.
        if p_match:
            return None

    if p_match:
        # 未知分P cid 时不能用 P1 字幕替代。
        return None

    return extract_bilibili_subtitle(url)


# ─── Pipeline ────────────────────────────────────────────────

async def fetch_subtitle(url: str, info, lang: str = None, fingerprint: str = None,
                         trace_id: str = "", refresh: bool = False, persist: bool = False) -> tuple[str, str, str]:
    """标准化字幕获取（DB 优先，减少重复 API 调用）。

    返回 (subtitle_text, source, language)。不含 AI 校正。
    refresh=True 跳过 DB 缓存强制重新获取（用于修复上游字幕错配等坏缓存）。
    """
    url = canonical_video_url(url, info)
    platform = info.extractor or ""

    # ── DB 缓存检查 ──
    cached_sub = None if refresh else get_subtitle_from_db(url)
    has_chinese_track = any(
        (track.lang or "").lower().replace("_", "-").removeprefix("ai-").startswith("zh")
        for track in (info.subtitles or [])
    )
    if (cached_sub and 'bilibili' in (info.extractor or '').lower()
            and _is_english_language(cached_sub.get("language"))
            and (has_chinese_track or cached_sub.get("source") == "bilibili_cc")):
        logger.info("忽略英文字幕缓存，重新检查 B站当前可用字幕")
        cached_sub = None
    if cached_sub:
        from core.subtitle_validation import validate_cached_subtitle, SubtitleIdentityError
        try:
            cached_sub = validate_cached_subtitle(url, cached_sub, info)
        except SubtitleIdentityError:
            cached_sub = None
    if cached_sub and len(cached_sub["full_text"].strip()) >= 50:
        if cached_sub["source"] == "bilibili_cc" and not re.search(r'\[\d{2}:\d{2}\]', cached_sub["full_text"]):
            logger.info(f"DB缓存的B站CC字幕缺少时间戳，跳过缓存重新获取")
        else:
            logger.info(f"字幕命中DB缓存 source={cached_sub['source']}")
            return cached_sub["full_text"], cached_sub["source"], cached_sub["language"]

    # ── Pipeline 1: Bilibili CC 字幕 API ──
    bilibili_sub = None
    bilibili_lookup_unavailable = False
    if 'bilibili' in (info.extractor or '').lower():
        with refresh_responses(refresh):
            bilibili_sub = await asyncio.to_thread(try_get_bilibili_cc_subtitle, url, info)
        if bilibili_sub:
            logger.info(f"B站CC字幕获取成功 has_subtitle={bilibili_sub.get('has_subtitle')} lang={bilibili_sub.get('language')}")
        else:
            bilibili_lookup_unavailable = True
            logger.info("B站CC字幕接口暂时不可用，先尝试其他原生字幕")
    if bilibili_sub and bilibili_sub['has_subtitle']:
        from core.subtitle_validation import validate_cached_subtitle
        validate_cached_subtitle(url, {'source': 'bilibili_cc', 'segments': bilibili_sub.get('segments'), 'full_text': bilibili_sub['text'], 'provenance': bilibili_sub.get('provenance')}, info)
        proof = bilibili_sub.get('provenance')
        if proof and proof.get('cid') and not getattr(info, 'parts', None):
            from core.models import VideoPart
            from core.cache import save_video_info_cache
            from core.video import selected_video_part_index
            info.parts = [VideoPart(index=selected_video_part_index(url, info) or 1,
                                    cid=int(proof['cid']), title=info.title, duration=info.duration)]
            save_video_info_cache(url, info)
        text = bilibili_sub['text']
        sub_lang = bilibili_sub.get('language', 'zh')
        if _is_english_language(sub_lang) and has_chinese_track:
            logger.info("B站 CC 返回英文字幕，但 yt-dlp 提供中文字幕轨道，改用中文轨道")
        else:
            if persist:
                save_subtitle_to_db(url, "bilibili_cc", sub_lang, text, info.title, platform,
                                    _build_part_info(url, info), bilibili_sub.get("segments"), provenance=bilibili_sub.get("provenance"))
            return text, "bilibili_cc", sub_lang

    # ── Pipeline 2: yt-dlp 原生字幕 ──
    if info.subtitles:
        selected = _select_subtitle_lang(info.subtitles, lang)
        if selected and selected.lang != 'danmaku':
            try:
                raw_content, ext = await asyncio.to_thread(
                    _download_subtitle_content, url, selected.lang, selected.is_auto
                )
                if ext == 'xml' or selected.lang == 'danmaku':
                    subtitle_text = _clean_danmaku_xml(raw_content)
                else:
                    subtitle_text = clean_subtitle_text(raw_content, ext)
                if subtitle_text and len(subtitle_text.strip()) >= 50:
                    source = "youtube_auto" if selected.is_auto else "ytdlp_native"
                    if persist:
                        save_subtitle_to_db(url, source, selected.lang, subtitle_text, info.title, platform,
                                            _build_part_info(url, info), extract_subtitle_segments(raw_content, ext))
                    logger.info(f"yt-dlp字幕获取成功 source={source}")
                    return subtitle_text, source, selected.lang
                raise ValueError("平台字幕为空或不完整")
            except BilibiliAccessBlocked:
                raise
            except Exception as e:
                logger.info(f"yt-dlp字幕获取失败: {e}")
                raise BilibiliSubtitleUnavailable("平台字幕获取暂时失败，请稍后重试；未启动语音转录") from e

    if bilibili_lookup_unavailable:
        raise BilibiliSubtitleUnavailable("B站字幕接口暂时不可用，请稍后重试；未启动语音转录")

    logger.info(f"没有可用的原生字幕，调用方可提交后台 Whisper 任务")
    return None, "", ""


def save_subtitle(url: str, info, subtitle_text: str, source: str, lang: str):
    """将字幕持久化到 DB。"""
    platform = info.extractor or ""
    _pi = _build_part_info(url, info=info)
    save_subtitle_to_db(url, source, lang, subtitle_text, info.title, platform, part_info=_pi)
