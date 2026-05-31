from fastapi import APIRouter, HTTPException, Query, Request
from typing import Optional
from core.task_queue import task_queue

router = APIRouter(prefix="/api", tags=["tasks"])


@router.get("/tasks/active")
async def get_active_tasks(request: Request):
    """返回当前用户所有活跃的后台转录任务。"""
    from core.task_manager import get_active_tasks as _get_tasks
    from api.auth_routes import get_identity
    identity = get_identity(request)
    tasks = _get_tasks(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"))
    return {"tasks": tasks}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, request: Request):
    """取消/删除一个后台任务（真正停止正在运行的 asyncio Task）。"""
    from core.task_manager import get_task, remove_task, _update_db_status
    from api.auth_routes import get_identity
    identity = get_identity(request)
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 验证任务归属
    if task.get("user_id") and task.get("user_id") != identity.get("user_id"):
        raise HTTPException(status_code=403, detail="无权操作此任务")
    if task.get("guest_id") and task.get("guest_id") != identity.get("guest_id"):
        raise HTTPException(status_code=403, detail="无权操作此任务")
    # 标记为已取消并清理（remove_task 会真正取消 asyncio Task）
    _update_db_status(task["url_hash"], "failed")
    remove_task(task_id)
    return {"status": "cancelled", "task_id": task_id}


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    # 先查内存任务管理器
    from core.task_manager import get_task
    task = get_task(task_id)
    if task:
        return task
    # 回退到旧的 task_queue
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
