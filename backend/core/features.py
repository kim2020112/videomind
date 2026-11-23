"""功能开关管理 — FEATURE_AI / FEATURE_WHISPER。

环境变量控制 + 运行时自动检测库可用性。
不可用的功能相关接口返回 503 feature_unavailable。
"""

import os
import shutil
from config import DEFAULT_GUEST_SECRET, GUEST_SECRET
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


def is_whisper_available() -> bool:
    """Whisper 功能是否可用：环境开关 + faster_whisper 库可导入 + 模型文件存在 + FFmpeg 可用。"""
    return not whisper_unavailable_reason()


def whisper_unavailable_reason() -> str:
    if not FEATURE_WHISPER:
        return "服务未启用语音转录"
    try:
        import faster_whisper  # noqa: F401
    except (ImportError, OSError) as exc:
        logger.warning("faster-whisper 加载失败: %s", exc)
        return "服务无法加载语音转录依赖"
    try:
        from core.whisper import is_model_available, model_directory
        if not is_model_available():
            logger.warning("Whisper 模型文件缺失: %s", model_directory())
            return "服务找不到完整的语音转录模型"
    except Exception:
        logger.exception("Whisper 模型检查失败")
        return "服务无法检查语音转录模型"
    return "" if is_ffmpeg_available() else "服务找不到 FFmpeg，无法处理音频"


def is_ffmpeg_available() -> bool:
    """检查 FFmpeg 是否在 PATH 中可用。"""
    return shutil.which("ffmpeg") is not None


def get_capabilities() -> dict:
    """返回当前服务能力状态，供 /api/capabilities 端点使用。"""
    return {
        "ai": is_ai_available(),
        "whisper": is_whisper_available(),
        "ffmpeg": is_ffmpeg_available(),
        "guest_access_enabled": bool(GUEST_SECRET) and GUEST_SECRET != DEFAULT_GUEST_SECRET,
    }
