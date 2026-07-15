"""Async scheduler that runs one Whisper subprocess at a time."""

import asyncio
import inspect
import json
import sys
import time
from pathlib import Path
from typing import Callable

from config import TEMP_DIR
from core import job_store
from core.logging_config import get_logger


logger = get_logger(__name__)


class JobScheduler:
    def __init__(
        self,
        command_factory: Callable | None = None,
        *,
        work_dir: Path | None = None,
        poll_interval: float = 1.0,
        cancel_poll_interval: float = 0.5,
        terminate_timeout: float = 5.0,
        on_completed: Callable | None = None,
        on_terminal: Callable | None = None,
    ):
        self.work_dir = Path(work_dir or (TEMP_DIR / "background_jobs"))
        self.command_factory = command_factory or self._default_command
        self.poll_interval = poll_interval
        self.cancel_poll_interval = cancel_poll_interval
        self.terminate_timeout = terminate_timeout
        self.on_completed = on_completed
        self.on_terminal = on_terminal
        self._loop_task: asyncio.Task | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._current_job_id: str | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self.work_dir.mkdir(parents=True, exist_ok=True)
        recovered = job_store.recover_interrupted_jobs()
        if recovered:
            logger.info("Recovered %s interrupted background job(s)", recovered)
        self._stopping = False
        self._loop_task = asyncio.create_task(self._run_loop(), name="background-job-scheduler")

    async def stop(self) -> None:
        self._stopping = True
        if self._process and self._process.returncode is None:
            await self._terminate_process(self._process)
        if self._loop_task:
            await self._loop_task
        self._loop_task = None

    async def _run_loop(self) -> None:
        while not self._stopping:
            processed = await self.run_once()
            if not processed:
                await asyncio.sleep(self.poll_interval)

    async def run_once(self) -> bool:
        job = job_store.claim_next_job()
        if not job:
            return False
        await self._run_job(job)
        return True

    async def _run_job(self, job: dict) -> None:
        job_id = job["task_id"]
        result_path = self.work_dir / f"{job_id}.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.unlink(missing_ok=True)
        command = self.command_factory(job, result_path)
        result = None
        last_error = ""
        self._current_job_id = job_id

        try:
            self._process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            while True:
                if job_store.is_cancel_requested(job_id):
                    await self._terminate_process(self._process)
                    job_store.update_job(
                        job_id,
                        status="cancelled",
                        progress=0,
                        message="任务已取消",
                    )
                    await self._notify_terminal(job_id, "cancelled")
                    return

                try:
                    line = await asyncio.wait_for(
                        self._process.stdout.readline(), timeout=self.cancel_poll_interval
                    )
                except asyncio.TimeoutError:
                    if self._process.returncode is not None:
                        break
                    continue

                if not line:
                    break
                event = self._parse_event(line.decode("utf-8", errors="replace").strip())
                if not event:
                    continue
                event_type = event.get("type")
                if event_type == "progress":
                    stage = event.get("stage", "transcribing")
                    if stage not in job_store.PROCESSING_STATUSES:
                        stage = "transcribing"
                    job_store.update_job(
                        job_id,
                        status=stage,
                        progress=event.get("progress", 0),
                        message=event.get("message", ""),
                    )
                elif event_type == "result":
                    result = event.get("result")
                    event_path = event.get("result_path")
                    if result is None and event_path:
                        result = self._read_result(Path(event_path))
                elif event_type == "error":
                    last_error = str(event.get("error") or "Whisper worker failed")

            return_code = await self._process.wait()
            if self._stopping:
                return
            if return_code != 0 or result is None:
                error = last_error or f"Whisper worker exited with code {return_code}"
                job_store.update_job(job_id, status="failed", error=error, message="处理失败")
                await self._notify_terminal(job_id, "failed", error)
                return

            job_store.update_job(job_id, status="generating", progress=96, message="正在整理结果")
            if job_store.is_cancel_requested(job_id):
                job_store.update_job(job_id, status="cancelled", progress=0, message="任务已取消")
                await self._notify_terminal(job_id, "cancelled")
                return
            if self.on_completed:
                completed = self.on_completed(job_store.get_job(job_id), result)
                if inspect.isawaitable(completed):
                    completed = await completed
                if completed is not None:
                    result = completed
            if job_store.is_cancel_requested(job_id):
                job_store.update_job(job_id, status="cancelled", progress=0, message="任务已取消")
                await self._notify_terminal(job_id, "cancelled")
                return
            job_store.update_job(
                job_id,
                status="done",
                progress=100,
                message="处理完成",
                result=result,
                error=None,
            )
            await self._notify_terminal(job_id, "done")
        except Exception as exc:
            if not self._stopping:
                logger.exception("Background job %s failed", job_id)
                job_store.update_job(
                    job_id,
                    status="failed",
                    error=str(exc),
                    message="处理失败",
                )
                await self._notify_terminal(job_id, "failed", str(exc))
        finally:
            self._process = None
            self._current_job_id = None
            result_path.unlink(missing_ok=True)

    async def _terminate_process(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=self.terminate_timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    async def _notify_terminal(self, job_id: str, status: str, error: str | None = None) -> None:
        if not self.on_terminal:
            return
        callback = self.on_terminal(job_store.get_job(job_id), status, error)
        if inspect.isawaitable(callback):
            await callback

    @staticmethod
    def _parse_event(line: str) -> dict | None:
        if not line:
            return None
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Ignoring malformed worker output: %s", line[:200])
            return None
        return event if isinstance(event, dict) else None

    @staticmethod
    def _read_result(path: Path) -> dict | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _default_command(job: dict, result_path: Path) -> list[str]:
        worker = Path(__file__).resolve().parents[1] / "workers" / "whisper_worker.py"
        command = [
            sys.executable,
            "-u",
            str(worker),
            "--job-id",
            job["task_id"],
            "--url",
            job["url"],
            "--result-path",
            str(result_path),
        ]
        if job.get("lang"):
            command.extend(["--language", job["lang"]])
        info = job.get("payload", {}).get("info") or {}
        audio_url = info.get("audio_stream_url")
        audio_expires_at = info.get("audio_stream_expires_at")
        if audio_url and (
            not audio_expires_at or float(audio_expires_at) > time.time()
        ):
            command.extend(["--audio-url", audio_url])
        return command
