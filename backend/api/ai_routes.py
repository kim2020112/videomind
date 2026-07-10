"""AI 相关路由 — 入库、RAG 问答。"""

import asyncio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from api.security import ensure_public_http_url, require_admin

router = APIRouter(prefix="/api", tags=["ai"])


class IngestRequest(BaseModel):
    url: str


class RAGQueryRequest(BaseModel):
    question: str
    video_id: Optional[int] = None


@router.post("/ingest")
async def ingest(req: IngestRequest, request: Request):
    require_admin(request)
    ensure_public_http_url(req.url)
    from services.ingest_service import ingest_video
    from core.task_queue import task_queue, TaskType, Task
    import uuid

    task_id = str(uuid.uuid4())[:8]
    task = Task(id=task_id, task_type=TaskType.INGEST)
    task_queue._tasks[task_id] = task

    async def _run():
        from core.task_queue import TaskStatus
        task.status = TaskStatus.RUNNING
        try:
            video_id = await ingest_video(req.url, task)
            task.status = TaskStatus.COMPLETED
            task.progress = 100
            task.result = {"video_id": video_id}
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)

    asyncio.create_task(_run())
    return {"task_id": task_id, "status": "submitted"}


@router.post("/rag/query/stream")
async def rag_query_stream(req: RAGQueryRequest, request: Request):
    require_admin(request)
    from services import rag_service

    async def generate():
        async for event_type, data in rag_service.stream_query(req.question, req.video_id):
            if event_type == "text":
                yield f"data: {data['text']}\n\n"
            elif event_type == "error":
                yield f"event: error\ndata: {data['message']}\n\n"
        yield "event: done\ndata: \n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
