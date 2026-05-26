"""关键问答对 Pipeline。"""

from core.pipeline import PipelineEvent
from core.ai_client import stream_qanda
from core.logging_config import get_logger

logger = get_logger(__name__)


def run_qanda(subtitle_text: str, video_title: str, trace_id: str = ""):
    """流式生成关键问答对。yield PipelineEvent，返回完整问答对列表。"""
    yield PipelineEvent("progress", {"stage": "qanda_generating", "message": "正在生成关键问答..."})

    qa_pairs = []
    try:
        for event_type, data in stream_qanda(subtitle_text, video_title):
            yield PipelineEvent(event_type, data)
            if event_type == "qa_pairs":
                qa_pairs = data
    except Exception as e:
        yield PipelineEvent("warn", {"message": f"问答对生成失败: {e}"})
        return []

    logger.info(f"关键问答对生成完成 count={len(qa_pairs)}")
    return qa_pairs
