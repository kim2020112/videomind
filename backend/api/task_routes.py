from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from core.task_queue import task_queue

router = APIRouter(prefix="/api", tags=["tasks"])


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    task = task_queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "id": task.id,
        "type": task.task_type.value,
        "status": task.status.value,
        "progress": task.progress,
        "message": task.message,
        "error": task.error,
        "video_id": task.video_id,
        "result": task.result,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }
