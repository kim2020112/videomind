"""RAG 问答服务 — 基于向量检索 + AI 生成。"""

from typing import Optional
from core.vectorstore import query_chunks
from core import ai_client


async def query(question: str, video_id: Optional[int] = None, top_k: int = 5) -> str:
    results = await query_chunks(question, n_results=top_k, video_id=video_id)
    if not results["documents"]:
        return "知识库中没有找到相关内容，请先添加视频。"
    return ai_client.rag_answer(question, results["documents"])


async def stream_query(question: str, video_id: Optional[int] = None, top_k: int = 5):
    results = await query_chunks(question, n_results=top_k, video_id=video_id)
    if not results["documents"]:
        yield ("text", {"text": "知识库中没有找到相关内容，请先添加视频。"})
        return
    for item in ai_client.stream_rag_answer(question, results["documents"]):
        yield item
