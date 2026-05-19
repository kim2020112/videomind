"""Faster-Whisper 转录模块 — 无字幕视频的兜底方案。

优先级：平台原生字幕 > 自动字幕 > Whisper 转录 > OCR（预留）

模型加载：
- 仅从本地 WHISPER_MODELS_DIR 加载，不联网下载
- 启动时检查模型目录，缺失时记录错误日志但不阻塞服务
"""

import asyncio
import os
import sys
import tempfile
import shutil

from config import WHISPER_MODEL, WHISPER_MODELS_DIR
from core.logging_config import get_logger

logger = get_logger(__name__)

_whisper_semaphore = asyncio.Semaphore(1)
_model_instance = None

_MODEL_DIR = os.path.join(str(WHISPER_MODELS_DIR), f"faster-whisper-{WHISPER_MODEL}")
_REQUIRED_FILES = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]


def is_model_available() -> bool:
    """检查本地 Whisper 模型文件是否完整。"""
    if not os.path.isdir(_MODEL_DIR):
        return False
    for f in _REQUIRED_FILES:
        if not os.path.isfile(os.path.join(_MODEL_DIR, f)):
            return False
    return True


# 启动时检查
if is_model_available():
    logger.info(f"模型已就绪: {_MODEL_DIR}")
else:
    missing = [f for f in _REQUIRED_FILES if not os.path.isfile(os.path.join(_MODEL_DIR, f))]
    logger.warning(f"模型不可用（{_MODEL_DIR}），缺失: {missing or '目录不存在'}。Whisper 转录已禁用。")


def _download_audio(url: str) -> str:
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

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            base = os.path.splitext(ydl.prepare_filename(info))[0]
            mp3_path = base + ".mp3"
            if os.path.exists(mp3_path):
                return mp3_path
            for f in os.listdir(tmpdir):
                fp = os.path.join(tmpdir, f)
                if os.path.isfile(fp) and not f.endswith(".part"):
                    return fp
            raise FileNotFoundError("音频下载后未找到输出文件")
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise


def _get_model():
    global _model_instance
    if _model_instance is None:
        from faster_whisper import WhisperModel
        _model_instance = WhisperModel(
            _MODEL_DIR, device="cpu", compute_type="int8",
            local_files_only=True,
        )
    return _model_instance


def transcribe(audio_path: str, language: str = None) -> str:
    """Faster-Whisper 转录音频为带时间戳的文本。仅使用本地模型，不联网。"""
    if not is_model_available():
        raise RuntimeError(
            f"Whisper 模型未就绪，请将模型文件放入 {_MODEL_DIR}"
        )

    model = _get_model()

    transcribe_opts = {"beam_size": 5, "vad_filter": True}
    if language:
        transcribe_opts["language"] = language

    segments, _ = model.transcribe(audio_path, **transcribe_opts)

    lines = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        mm = int(seg.start // 60)
        ss = int(seg.start % 60)
        lines.append(f"[{mm:02d}:{ss:02d}] {text}")

    return "\n".join(lines)


def transcribe_video(url: str, language: str = None) -> str:
    """下载视频音频 + Whisper 转录，返回字幕文本。用完自动清理临时文件。"""
    if not is_model_available():
        raise RuntimeError(
            f"Whisper 模型未就绪，请将模型文件放入 {_MODEL_DIR}"
        )
    audio_path = _download_audio(url)
    tmpdir = os.path.dirname(audio_path)
    try:
        return transcribe(audio_path, language)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


async def transcribe_video_async(url: str, language: str = None) -> str:
    """异步安全版本：全局 Semaphore(1) 保护，防止并发转录打爆 CPU。"""
    loop = asyncio.get_event_loop()
    async with _whisper_semaphore:
        return await loop.run_in_executor(None, transcribe_video, url, language)
