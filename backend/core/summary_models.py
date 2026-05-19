"""AI 总结功能的数据模型（独立文件，不修改已有 models.py）。"""

from pydantic import BaseModel
from typing import Optional


class SummarizeRequest(BaseModel):
    url: str
    lang: Optional[str] = None
    force: bool = False
    mode: str = "full"  # "full" | "summary" | "mindmap" | "notes" | "subtitle"


class ChapterItem(BaseModel):
    time: Optional[str] = ""
    title: str
    content: str


class MindMapNode(BaseModel):
    title: str
    children: list = []


class SummaryResult(BaseModel):
    summary: str
    chapters: list[ChapterItem] = []
    mindmap: Optional[MindMapNode] = None


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    subtitle_text: str
    question: str
    history: list[ChatMessage] = []
