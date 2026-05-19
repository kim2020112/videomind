"""学习笔记 Pipeline。

流式生成笔记（纯文本，不含时间戳）。
"""

from core.pipeline import PipelineEvent
from core.ai_client import stream_generate_notes
from core.logging_config import get_logger

logger = get_logger(__name__)


def run_notes(subtitle_text: str, video_title: str, canonical_url: str = "",
              trace_id: str = ""):
    """流式生成学习笔记。yield PipelineEvent，返回完整笔记文本。"""
    yield PipelineEvent("progress", {"stage": "notes_generating", "message": "正在生成学习笔记..."})

    notes_full = ""
    try:
        for event_type, data in stream_generate_notes(subtitle_text, video_title):
            yield PipelineEvent(event_type, data)
            if event_type == "notes_text":
                notes_full += data.get("text", "")
    except Exception as e:
        yield PipelineEvent("warn", {"message": f"笔记生成失败: {e}"})
        return ""

    logger.info(f"学习笔记生成完成 len={len(notes_full)}")
    return notes_full
