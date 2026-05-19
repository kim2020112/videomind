import asyncio
import uuid
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Callable, Any
from datetime import datetime


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskType(str, Enum):
    INGEST = "ingest"
    SUBTITLE = "subtitle"
    SUMMARIZE = "summarize"
    VECTORIZE = "vectorize"


@dataclass
class Task:
    id: str
    task_type: TaskType
    video_id: Optional[int] = None
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    message: str = ""
    error: Optional[str] = None
    result: Any = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TaskQueue:
    def __init__(self, max_concurrent: int = 2):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._tasks: dict[str, Task] = {}
        self._handlers: dict[TaskType, Callable] = {}
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._started = False

    def register_handler(self, task_type: TaskType, handler: Callable):
        self._handlers[task_type] = handler

    async def submit(self, task_type: TaskType, video_id: int = None) -> str:
        task_id = str(uuid.uuid4())[:8]
        task = Task(id=task_id, task_type=task_type, video_id=video_id)
        self._tasks[task_id] = task
        await self._queue.put(task)
        if not self._started:
            self._start_workers()
        return task_id

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def _start_workers(self):
        for _ in range(self._max_concurrent):
            asyncio.create_task(self._worker())
        self._started = True

    async def _worker(self):
        while True:
            task = await self._queue.get()
            async with self._semaphore:
                await self._execute(task)
            self._queue.task_done()

    async def _execute(self, task: Task):
        handler = self._handlers.get(task.task_type)
        if not handler:
            task.status = TaskStatus.FAILED
            task.error = f"No handler for {task.task_type}"
            return
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        try:
            result = await handler(task)
            task.status = TaskStatus.COMPLETED
            task.progress = 100.0
            task.result = result
            task.completed_at = datetime.now()
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now()


task_queue = TaskQueue()
