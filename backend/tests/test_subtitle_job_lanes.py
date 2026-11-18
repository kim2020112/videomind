"""Real concurrency regressions for the native-subtitle and long-job lanes."""

import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

import database
from core import job_store
from core.job_scheduler import JobScheduler


@pytest.fixture(autouse=True)
def isolated_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(job_store, "DB_PATH", tmp_path / "jobs.db")
    database.init_db()


def create(name, *, owner=1, targets=None, **payload):
    return job_store.create_job(name, f"https://example.com/{name}", user_id=owner,
                                job_type="learning", payload={"targets": targets or [], **payload})


def test_lanes_have_independent_atomic_single_slots():
    heavy = create("heavy", targets=["summary"])
    short = create("short")
    create("short-next")
    assert job_store.claim_next_job("default")["task_id"] == heavy
    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(lambda _: job_store.claim_next_job("subtitle"), range(2)))
    assert [job["task_id"] for job in claims if job] == [short]
    assert job_store.claim_next_job("default") is None


def test_same_video_is_exclusive_without_blocking_other_videos():
    heavy = create("same", targets=["notes"])
    blocked = create("same", owner=2)
    available = create("other")
    assert job_store.claim_next_job("default")["task_id"] == heavy
    assert job_store.claim_next_job("subtitle")["task_id"] == available
    job_store.update_job(available, status="done")
    assert job_store.claim_next_job("subtitle") is None
    job_store.update_job(heavy, status="done")
    assert job_store.claim_next_job("subtitle")["task_id"] == blocked


def test_transcription_and_description_stay_in_long_lane():
    transcription = create("whisper", allow_transcription=True)
    description = create("description", input_source="description")
    short = create("native")
    assert job_store.claim_next_job("subtitle")["task_id"] == short
    assert job_store.claim_next_job("default")["task_id"] == transcription
    job_store.update_job(transcription, status="done")
    assert job_store.claim_next_job("default")["task_id"] == description


def test_confirmation_releases_short_lane_and_resumes_in_long_lane():
    waiting = create("waiting")
    assert job_store.claim_next_job("subtitle")["task_id"] == waiting
    job_store.update_job(waiting, status="awaiting_confirmation")
    next_short = create("next")
    assert job_store.claim_next_job("subtitle")["task_id"] == next_short
    job_store.update_job(waiting, status="queued", payload={"targets": [], "allow_transcription": True})
    assert job_store.claim_next_job("default")["task_id"] == waiting


def test_interrupted_admission_is_not_executed_after_recovery():
    pending = create("pending", _admission_pending=True)
    with database.get_db() as conn:
        conn.execute("INSERT INTO learning_usage(operation_id, guest_id, status) VALUES (?, ?, 'reserved')",
                     (pending, "test"))
    assert job_store.get_queue_position(pending) is None
    assert job_store.claim_next_job("subtitle") is None
    job_store.recover_interrupted_jobs()
    assert job_store.get_job(pending)["status"] == "failed"
    with database.get_db() as conn:
        assert conn.execute("SELECT count(*) FROM learning_usage").fetchone()[0] == 0
    assert job_store.claim_next_job("subtitle") is None


def test_native_task_finishes_while_long_handler_is_blocked(tmp_path):
    async def scenario():
        started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
        heavy = create("long", targets=["summary"])
        short = create("native")

        async def handler(job, scheduler):
            if job["task_id"] == heavy:
                started.set()
                await release.wait()
            else:
                finished.set()
            return {}

        long = JobScheduler(lane="default", work_dir=tmp_path, handlers={"learning": handler})
        native = JobScheduler(lane="subtitle", work_dir=tmp_path, handlers={"learning": handler})
        running = asyncio.create_task(long.run_once())
        try:
            await asyncio.wait_for(started.wait(), 1)
            await asyncio.wait_for(native.run_once(), 0.5)
            assert finished.is_set()
            assert job_store.get_job(short)["status"] == "done"
            assert job_store.get_job(heavy)["status"] == "downloading"
            assert long._current_job_id == heavy
            assert native._current_job_id is None
        finally:
            release.set()
            await running

    asyncio.run(scenario())


def test_enqueue_and_shutdown_wake_idle_scheduler_without_polling(tmp_path):
    async def scenario():
        idle, finished = asyncio.Event(), asyncio.Event()

        async def handler(job, scheduler):
            finished.set()
            return {}

        scheduler = JobScheduler(lane="subtitle", work_dir=tmp_path, poll_interval=30,
                                 handlers={"learning": handler})
        original = scheduler.run_once

        async def run_once():
            result = await original()
            if not result:
                idle.set()
            return result

        scheduler.run_once = run_once
        await scheduler.start()
        try:
            await asyncio.wait_for(idle.wait(), 1)
            task_id = await asyncio.to_thread(create, "wake")
            await asyncio.wait_for(finished.wait(), 0.5)
            assert job_store.get_job(task_id)["status"] == "done"
        finally:
            await asyncio.wait_for(scheduler.stop(), 0.5)

    asyncio.run(scenario())


def test_startup_only_recovers_once_for_both_lanes(tmp_path):
    async def scenario():
        schedulers = [JobScheduler(lane=lane, work_dir=tmp_path) for lane in ("default", "subtitle")]
        with patch.object(job_store, "recover_interrupted_jobs", wraps=job_store.recover_interrupted_jobs) as recover:
            try:
                await schedulers[0].start()
                await schedulers[1].start(recover_interrupted=False)
                recover.assert_called_once()
            finally:
                await asyncio.gather(*(scheduler.stop() for scheduler in schedulers))

    asyncio.run(scenario())


def test_cancelling_long_worker_does_not_cancel_native_lane(tmp_path):
    async def scenario():
        heavy = job_store.create_job("worker", "https://example.com/worker", user_id=1)
        short = create("native")
        native_started, native_release = asyncio.Event(), asyncio.Event()

        async def handler(job, scheduler):
            native_started.set()
            await native_release.wait()
            return {}

        command = [sys.executable, "-u", "-c",
                   "import json,time; print(json.dumps({'type':'progress','stage':'transcribing'}),flush=True); time.sleep(20)"]
        long = JobScheduler(lambda *_: command, lane="default", work_dir=tmp_path,
                            cancel_poll_interval=0.02, terminate_timeout=0.2)
        native = JobScheduler(lane="subtitle", work_dir=tmp_path, handlers={"learning": handler})
        long_task = asyncio.create_task(long.run_once())
        native_task = asyncio.create_task(native.run_once())
        try:
            await asyncio.wait_for(native_started.wait(), 1)
            job_store.request_cancel(heavy, user_id=1)
            await asyncio.wait_for(long_task, 2)
            assert job_store.get_job(heavy)["status"] == "cancelled"
            assert not native_task.done()
            native_release.set()
            await asyncio.wait_for(native_task, 1)
            assert job_store.get_job(short)["status"] == "done"
        finally:
            native_release.set()
            await asyncio.gather(long_task, native_task)

    asyncio.run(scenario())
