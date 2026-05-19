"""标签提取 Pipeline。"""

from core.tag_extractor import extract_tags, detect_platform
from core.cache import save_tags
from core.logging_config import get_logger

logger = get_logger(__name__)


def run_tags(url: str, title: str, summary_text: str, trace_id: str = "") -> list[str]:
    """提取标签并保存。失败返回空列表。"""
    try:
        tags = extract_tags(title, summary_text, url)
        if tags:
            save_tags(url, tags)
            logger.info(f"标签提取完成 tags={tags}")
        return tags
    except Exception as e:
        logger.warning(f"标签提取失败: {e}")
        return []
