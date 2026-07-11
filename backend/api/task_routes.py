from fastapi import APIRouter, HTTPException, Request

from api.security import require_identity
from core.job_store import get_job, list_active_jobs, request_cancel
from core.background_pipeline import update_terminal_history

router = APIRouter(prefix="/api", tags=["tasks"])


def _owner(identity: dict) -> dict:
    return {
        "user_id": identity.get("user_id"),
        "guest_id": identity.get("guest_id"),
    }


@router.get("/tasks/active")
async def get_active_tasks(request: Request):
    """返回当前用户排队中和处理中的后台任务。"""
    identity = require_identity(request)
    return {"tasks": list_active_jobs(**_owner(identity))}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, request: Request):
    """取消排队任务，或请求终止正在运行的子进程。"""
    identity = require_identity(request)
    owner = _owner(identity)
    job = get_job(task_id, **owner)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not request_cancel(task_id, **owner):
        raise HTTPException(status_code=409, detail="任务已结束，无法取消")
    updated = get_job(task_id, **owner)
    await update_terminal_history(updated, "cancelled")
    status = "cancelled" if updated and updated["status"] == "cancelled" else "cancelling"
    return {"status": status, "task_id": task_id}


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str, request: Request):
    identity = require_identity(request)
    job = get_job(task_id, **_owner(identity))
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job
