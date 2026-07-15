import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import config
import database
from core import job_store


def fake_command(lines: list[str], exit_code: int = 0, delay: float = 0) -> list[str]:
    script = ["import sys,time"]
    for line in lines:
        script.append(f"print({line!r}, flush=True)")
        if delay:
            script.append(f"time.sleep({delay})")
    script.append(f"sys.exit({exit_code})")
    return [sys.executable, "-u", "-c", ";".join(script)]


class JobSchedulerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        db_path = root / "knowledge.db"
        config.DB_PATH = db_path
        database.DB_PATH = db_path
        job_store.DB_PATH = db_path
        database.init_db()
        self.work_dir = root / "jobs"

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_command_passes_cached_audio_stream_to_worker(self):
        from core.job_scheduler import JobScheduler

        audio_url = "https://audio.example.com/best.m4s?deadline=9999999999"
        job = {
            "task_id": "job-audio",
            "url": "https://www.bilibili.com/video/BV1demo",
            "lang": "",
            "payload": {
                "info": {
                    "audio_stream_url": audio_url,
                    "audio_stream_expires_at": 9999999999,
                }
            },
        }

        command = JobScheduler._default_command(job, self.work_dir / "result.json")

        self.assertIn("--audio-url", command)
        self.assertEqual(audio_url, command[command.index("--audio-url") + 1])

    async def test_completed_child_progress_marks_job_done(self):
        from core.job_scheduler import JobScheduler

        job_id = job_store.create_job("hash-1", "https://example.com/1", user_id=1)
        command = fake_command(
            [
                json.dumps({"type": "progress", "stage": "transcribing", "progress": 45, "message": "working"}),
                json.dumps({"type": "result", "result": {"subtitle_text": "hello"}}),
            ]
        )
        scheduler = JobScheduler(lambda _job, _path: command, work_dir=self.work_dir)

        await scheduler.run_once()

        job = job_store.get_job(job_id, user_id=1)
        self.assertEqual("done", job["status"])
        self.assertEqual(100, job["progress"])
        self.assertEqual("hello", job["result"]["subtitle_text"])

    async def test_malformed_output_is_ignored_when_result_is_valid(self):
        from core.job_scheduler import JobScheduler

        job_id = job_store.create_job("hash-1", "https://example.com/1", user_id=1)
        command = fake_command(
            [
                "not-json",
                json.dumps({"type": "result", "result": {"subtitle_text": "ok"}}),
            ]
        )
        scheduler = JobScheduler(lambda _job, _path: command, work_dir=self.work_dir)

        await scheduler.run_once()

        self.assertEqual("done", job_store.get_job(job_id, user_id=1)["status"])

    async def test_child_failure_is_terminal_without_retry(self):
        from core.job_scheduler import JobScheduler

        job_id = job_store.create_job("hash-1", "https://example.com/1", user_id=1)
        command = fake_command(
            [json.dumps({"type": "error", "error": "model failed"})],
            exit_code=2,
        )
        scheduler = JobScheduler(lambda _job, _path: command, work_dir=self.work_dir)

        await scheduler.run_once()

        job = job_store.get_job(job_id, user_id=1)
        self.assertEqual("failed", job["status"])
        self.assertIn("model failed", job["error"])
        self.assertEqual(0, job["attempts"])

    async def test_cancellation_terminates_running_child(self):
        from core.job_scheduler import JobScheduler

        job_id = job_store.create_job("hash-1", "https://example.com/1", user_id=1)
        command = fake_command(
            [json.dumps({"type": "progress", "stage": "transcribing", "progress": 10})],
            delay=10,
        )
        scheduler = JobScheduler(
            lambda _job, _path: command,
            work_dir=self.work_dir,
            cancel_poll_interval=0.05,
            terminate_timeout=0.2,
        )

        running = asyncio.create_task(scheduler.run_once())
        for _ in range(50):
            job = job_store.get_job(job_id, user_id=1)
            if job["status"] == "transcribing":
                break
            await asyncio.sleep(0.02)
        self.assertTrue(job_store.request_cancel(job_id, user_id=1))
        await asyncio.wait_for(running, timeout=3)

        self.assertEqual("cancelled", job_store.get_job(job_id, user_id=1)["status"])

    async def test_concurrent_run_once_claims_only_one_job(self):
        from core.job_scheduler import JobScheduler

        job_store.create_job("hash-1", "https://example.com/1", user_id=1)
        job_store.create_job("hash-2", "https://example.com/2", user_id=1)
        calls = []
        command = fake_command(
            [json.dumps({"type": "result", "result": {"subtitle_text": "ok"}})],
            delay=0.2,
        )

        def command_factory(job, _path):
            calls.append(job["task_id"])
            return command

        scheduler = JobScheduler(command_factory, work_dir=self.work_dir)
        await asyncio.gather(scheduler.run_once(), scheduler.run_once())

        self.assertEqual(1, len(calls))
        self.assertEqual(1, len(job_store.list_active_jobs(user_id=1)))

    async def test_cancel_requested_during_generation_wins_over_completion(self):
        from core.job_scheduler import JobScheduler

        job_id = job_store.create_job("hash-1", "https://example.com/1", user_id=1)
        command = fake_command(
            [json.dumps({"type": "result", "result": {"subtitle_text": "ok"}})]
        )

        async def slow_completion(_job, result):
            await asyncio.sleep(0.2)
            return result

        scheduler = JobScheduler(
            lambda _job, _path: command,
            work_dir=self.work_dir,
            on_completed=slow_completion,
        )
        running = asyncio.create_task(scheduler.run_once())
        for _ in range(50):
            job = job_store.get_job(job_id, user_id=1)
            if job["status"] == "generating":
                break
            await asyncio.sleep(0.02)
        self.assertTrue(job_store.request_cancel(job_id, user_id=1))
        await running

        self.assertEqual("cancelled", job_store.get_job(job_id, user_id=1)["status"])


if __name__ == "__main__":
    unittest.main()
