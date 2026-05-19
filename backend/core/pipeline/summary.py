"""AI 摘要 Pipeline。

短视频：直接 stream_summarize。
长视频（字幕 >60000 字符）：chunk summary 首片优先。
"""

from core.pipeline import PipelineEvent
from core.ai_client import stream_summarize, stream_chunk_summaries, _split_text
from core.logging_config import get_logger

logger = get_logger(__name__)


def run_summary(subtitle_text: str, video_title: str, trace_id: str = ""):
    """AI 摘要生成。yield PipelineEvent。

    短视频：直接摘要。
    长视频：首片优先（初步摘要）→ 完整摘要覆盖。
    """
    chunks = _split_text(subtitle_text)

    if len(chunks) > 1:
        yield from _run_chunked(subtitle_text, video_title, trace_id)
    else:
        yield from _run_single(subtitle_text, video_title, trace_id)


def _run_single(subtitle_text: str, video_title: str, trace_id: str):
    """短视频直接摘要。"""
    yield PipelineEvent("progress", {"stage": "summary_generating", "message": "正在生成 AI 摘要..."})
    result_data = {}
    summary_failed = False

    for event_type, data in stream_summarize(subtitle_text, video_title):
        if event_type == "error":
            yield PipelineEvent("warn", {"message": f"AI 摘要生成失败: {data.get('message', '未知错误')}，视频和字幕仍可正常使用"})
            summary_failed = True
            break
        if event_type == "result":
            result_data = data
        yield PipelineEvent(event_type, data)

    if not summary_failed:
        logger.info(f"AI 摘要生成完成")


def _run_chunked(subtitle_text: str, video_title: str, trace_id: str):
    """长视频 chunk summary 首片优先。"""
    result_data = {}
    summary_failed = False

    for cevt, cdata in stream_chunk_summaries(subtitle_text, video_title):
        if cevt == "first_chunk_ready":
            yield PipelineEvent("progress", {
                "stage": "summary_initial",
                "message": f"基于视频前段内容（约{100 // cdata['total']}%），生成初步摘要...",
            })
            for sevt, sdata in stream_summarize(cdata["text"], video_title):
                if sevt == "error":
                    yield PipelineEvent("warn", {"message": f"AI 摘要生成失败: {sdata.get('message', '未知错误')}，视频和字幕仍可正常使用"})
                    summary_failed = True
                    break
                if sevt == "result":
                    sdata["is_partial"] = True
                    result_data = sdata
                yield PipelineEvent(sevt, sdata)

        elif cevt == "chunk_progress":
            yield PipelineEvent("progress", {
                "stage": "chunk_progress",
                "message": f"字幕片段处理中 ({cdata['index'] + 1}/{cdata['total']})...",
            })

        elif cevt == "all_chunks_ready":
            if not summary_failed:
                yield PipelineEvent("progress", {
                    "stage": "summary_final",
                    "message": "正在基于完整字幕生成全面摘要...",
                })
                for sevt, sdata in stream_summarize(cdata["text"], video_title):
                    if sevt == "error":
                        yield PipelineEvent("warn", {"message": f"AI 摘要生成失败: {sdata.get('message', '未知错误')}，视频和字幕仍可正常使用"})
                        summary_failed = True
                        break
                    if sevt == "result":
                        sdata["is_partial"] = False
                        result_data = sdata
                    yield PipelineEvent(sevt, sdata)

    if not summary_failed:
        logger.info(f"AI 摘要生成完成（长视频 chunk）")
