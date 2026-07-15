"""Faster-Whisper 转录模块 — 无字幕视频的兜底方案。

优先级：平台原生字幕 > 自动字幕 > Whisper 转录 > OCR（预留）

模型加载：
- 仅从本地 WHISPER_MODELS_DIR 加载，不联网下载
- 启动时检查模型目录，缺失时记录错误日志但不阻塞服务
"""

import os
import tempfile
import shutil

from config import WHISPER_MODEL, WHISPER_MODELS_DIR
from core.logging_config import get_logger

logger = get_logger(__name__)

def estimate_transcribe_time(duration_seconds: int) -> int:
    """预估 Whisper 转录耗时（秒）。CPU int8 small 模型约 2-3 倍实时速度，加上下载和校正开销。"""
    return max(60, int(duration_seconds * 3.5))

_REQUIRED_FILES = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]


def model_directory() -> str:
    return os.path.join(str(WHISPER_MODELS_DIR), f"faster-whisper-{WHISPER_MODEL}")


def is_model_available() -> bool:
    """检查本地 Whisper 模型文件是否完整。"""
    model_dir = model_directory()
    if not os.path.isdir(model_dir):
        return False
    for f in _REQUIRED_FILES:
        if not os.path.isfile(os.path.join(model_dir, f)):
            return False
    return True


def _download_audio(url: str, *, audio_url: str | None = None) -> str:
    """用 yt-dlp 下载视频音频（仅音频，mp3）。返回音频文件路径。"""
    import yt_dlp

    tmpdir = tempfile.mkdtemp(prefix="whisper_audio_")
    outtmpl = os.path.join(tmpdir, "%(id)s.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    if audio_url and "bilibili.com" in url.lower():
        ydl_opts["http_headers"] = {
            "Referer": "https://www.bilibili.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
            ),
        }

    try:
        targets = [audio_url, url] if audio_url else [url]
        last_error = None
        for target in targets:
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(target, download=True)
                    base = os.path.splitext(ydl.prepare_filename(info))[0]
                    mp3_path = base + ".mp3"
                    if os.path.exists(mp3_path):
                        return mp3_path
                    for f in os.listdir(tmpdir):
                        fp = os.path.join(tmpdir, f)
                        if os.path.isfile(fp) and not f.endswith(".part"):
                            return fp
                    raise FileNotFoundError("音频下载后未找到输出文件")
            except Exception as exc:
                last_error = exc
        raise last_error or RuntimeError("音频下载失败")
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise


__all__ = ["estimate_transcribe_time", "is_model_available", "model_directory"]
