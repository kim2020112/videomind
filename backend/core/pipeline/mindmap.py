"""思维导图 Pipeline。"""

from core.ai_client import generate_mindmap
from core.logging_config import get_logger

logger = get_logger(__name__)


def run_mindmap(subtitle_text: str, video_title: str, trace_id: str = "") -> str:
    """生成思维导图 Markdown。失败返回空字符串。"""
    try:
        mindmap_md = generate_mindmap(subtitle_text, video_title)
        logger.info(f"思维导图生成完成")
        return mindmap_md
    except Exception as e:
        logger.info(f"思维导图生成失败: {e}")
        return ""
