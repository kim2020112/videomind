"""功能开关管理 — FEATURE_AI / FEATURE_WHISPER。

环境变量控制 + 运行时自动检测库可用性。
不可用的功能相关接口返回 503 feature_unavailable。
"""

import os
import shutil
from functools import lru_cache
from core.logging_config import get_logger

logger = get_logger(__name__)

# ── 环境变量开关（默认全部开启，向后兼容）──

FEATURE_AI = os.getenv("FEATURE_AI", "true").lower() == "true"
FEATURE_WHISPER = os.getenv("FEATURE_WHISPER", "true").lower() == "true"


def is_ai_available() -> bool:
    """AI 功能是否可用：环境开关 + anthropic 库可导入 + API Key 已配置。"""
    if not FEATURE_AI:
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        logger.warning("FEATURE_AI=true 但 anthropic 库未安装，AI 功能自动禁用")
        return False
    from core.ai_config import get_effective_api_key

    if not get_effective_api_key().strip():
        logger.warning("FEATURE_AI=true 但未配置有效 API Key，AI 功能自动禁用")
        return False
    return True


@lru_cache(maxsize=1)
def is_whisper_available() -> bool:
    """Whisper 功能是否可用：环境开关 + faster_whisper 库可导入 + 模型文件存在 + FFmpeg 可用。"""
    if not FEATURE_WHISPER:
        return False
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        logger.warning("FEATURE_WHISPER=true 但 faster-whisper 库未安装，Whisper 功能自动禁用")
        return False
    # 检查模型文件
    try:
        from core.whisper import is_model_available
        if not is_model_available():
            return False
    except Exception:
        return False
    # 检查 FFmpeg
    return is_ffmpeg_available()


@lru_cache(maxsize=1)
def is_ffmpeg_available() -> bool:
    """检查 FFmpeg 是否在 PATH 中可用。"""
    return shutil.which("ffmpeg") is not None


def get_capabilities() -> dict:
    """返回当前服务能力状态，供 /api/capabilities 端点使用。"""
    return {
        "ai": is_ai_available(),
        "whisper": is_whisper_available(),
        "ffmpeg": is_ffmpeg_available(),
    }
