"""AI 总结功能的路由（独立文件，不修改已有 routes.py）。

复用 routes.py 中的 extract_url、_download_subtitle_content、downloader 实例。
"""

import asyncio
import datetime

from fastapi import APIRouter, HTTPException

from core.summary_models import SummarizeRequest, SummaryResult, ChapterItem, MindMapNode
from core.summarizer import clean_subtitle_text, summarize_subtitle, summarize_from_description

# 复用已有模块中的工具函数和实例
from api.routes import extract_url, _download_subtitle_content, downloader

router = APIRouter()

# 每日免费次数限制（内存计数，重启清零）
_summarize_usage: dict[str, int] = {}
_SUMMARIZE_FREE_LIMIT = 999999  # 开发阶段放行，后续从 .env 读取


def _select_subtitle_lang(subtitles, preferred: str = None):
    """选择最佳字幕语言。优先中文，其次英文，最后取第一个。"""
    if preferred:
        for sub in subtitles:
            if sub.lang == preferred or sub.lang.startswith(preferred):
                return sub
    for sub in subtitles:
        if sub.lang.startswith('zh') or sub.lang.startswith('zh-Hans'):
            return sub
    for sub in subtitles:
        if sub.lang.startswith('en'):
            return sub
    return subtitles[0] if subtitles else None


def get_summarize_usage() -> int:
    """获取今日已用次数。"""
    today = datetime.date.today().isoformat()
    return _summarize_usage.get(today, 0)


def inc_summarize_usage():
    """今日使用次数 +1。"""
    today = datetime.date.today().isoformat()
    _summarize_usage[today] = _summarize_usage.get(today, 0) + 1


@router.post("/api/summarize", response_model=SummaryResult)
async def summarize_video(req: SummarizeRequest):
    """AI 视频总结：提取字幕 -> DeepSeek 生成摘要/章节/思维导图。"""
    today = datetime.date.today().isoformat()
    used = _summarize_usage.get(today, 0)
    if used >= _SUMMARIZE_FREE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"今日免费次数已用完（每日 {_SUMMARIZE_FREE_LIMIT} 次），请明天再试或升级 Pro"
        )

    try:
        url = extract_url(req.url)

        info = downloader.parse_info(url)

        # 无字幕时降级：用视频标题+简介生成基础总结
        if not info.subtitles:
            if not info.description or len(info.description.strip()) < 20:
                raise HTTPException(status_code=400, detail="该视频没有字幕也没有简介，无法生成 AI 总结")
            result = await asyncio.get_event_loop().run_in_executor(
                None, summarize_from_description, info.title, info.description
            )
            _summarize_usage[today] = used + 1
            chapters = [ChapterItem(**ch) for ch in result.get("chapters", [])]
            mindmap = MindMapNode(title=info.title[:20], children=[])
            return SummaryResult(
                summary="⚠️ 该视频无字幕，以下总结基于视频简介生成，仅供参考。\n\n" + result.get("summary", ""),
                chapters=chapters,
                mindmap=mindmap,
            )

        selected = _select_subtitle_lang(info.subtitles, req.lang)
        if not selected:
            raise HTTPException(status_code=400, detail="未找到合适的字幕轨道")

        raw_content, ext = await asyncio.get_event_loop().run_in_executor(
            None, _download_subtitle_content, url, selected.lang, selected.is_auto
        )

        clean_text = clean_subtitle_text(raw_content, ext)
        if len(clean_text.strip()) < 50:
            # 字幕内容无效（如弹幕），也降级到描述总结
            if info.description and len(info.description.strip()) >= 20:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, summarize_from_description, info.title, info.description
                )
                _summarize_usage[today] = used + 1
                chapters = [ChapterItem(**ch) for ch in result.get("chapters", [])]
                mindmap = MindMapNode(title=info.title[:20], children=[])
                return SummaryResult(
                    summary="⚠️ 该视频字幕内容不可用（可能为弹幕格式），以下总结基于视频简介生成，仅供参考。\n\n" + result.get("summary", ""),
                    chapters=chapters,
                    mindmap=mindmap,
                )
            raise HTTPException(status_code=400, detail="字幕内容过短，无法生成有效总结")

        result = await asyncio.get_event_loop().run_in_executor(
            None, summarize_subtitle, clean_text, info.title
        )

        _summarize_usage[today] = used + 1

        chapters = [ChapterItem(**ch) for ch in result.get("chapters", [])]
        mindmap = MindMapNode(title="视频内容", children=[])

        return SummaryResult(
            summary=result.get("summary", ""),
            chapters=chapters,
            mindmap=mindmap,
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 总结失败: {str(e)}")
