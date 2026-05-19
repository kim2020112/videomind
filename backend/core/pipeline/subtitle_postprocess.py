"""字幕后处理 — AI 校正。

Whisper 转录后利用视频标题/简介作为上下文进行 AI 校正。
校正失败自动降级到原始文本。
"""

import asyncio

from core.ai_client import correct_subtitle
from config import SUBTITLE_CORRECTION_ENABLED
from core.logging_config import get_logger

logger = get_logger(__name__)


async def correct_subtitle_text(text: str, title: str = "", description: str = "",
                                trace_id: str = "") -> str:
    """AI 字幕校正。失败返回原文。"""
    if not SUBTITLE_CORRECTION_ENABLED:
        return text
    if not text or len(text.strip()) < 20:
        return text

    try:
        corrected = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None, correct_subtitle, text, title, description
            ),
            timeout=60,
        )
        if corrected and len(corrected.strip()) >= 20:
            logger.info(f"AI字幕校正完成")
            return corrected
        logger.info(f"AI字幕校正结果过短，使用原文")
        return text
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"AI字幕校正失败，使用原文: {e}")
        return text
