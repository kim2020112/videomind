import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import config
import database
from core import job_store
from core.blogger import batches, batch_runner, store
from core.job_scheduler import JobCancelled

IDENTITY = {"user_id": 1, "guest_id": None}


class FakeCatalogClient:
    def __init__(self, *args, **kwargs):
        pass

    def parts(self, bvid):
        return {"title": bvid}, [{"cid": 11, "page": 1, "part": "P1", "duration": 60}]


class StubScheduler:
    def __init__(self):
        self.work_dir = Path(tempfile.gettempdir()) / "batch-runner-tests"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.whisper_calls = []
        self.run_worker_subprocess = AsyncMock(side_effect=self._whisper)

    async def _whisper(self, job_id, command):
        self.whisper_calls.append((job_id, command))
        return {"subtitle_text": "这是一段足够长的转录文本" * 5, "language": "zh"}

    def _default_command(self, job, result_path):
        return ["fake-whisper", job["url"]]


class BatchRunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (config.DB_PATH, database.DB_PATH, job_store.DB_PATH)
        config.DB_PATH = database.DB_PATH = job_store.DB_PATH = root / "knowledge.db"
        database.init_db()
        self.creator_id = store.upsert_creator("bilibili", "100")
        self.video_id = store.upsert_video(self.creator_id, {"bvid": "BV1test", "title": "测试视频"})
        self.scheduler = StubScheduler()

    def tearDown(self):
        self.tmp.cleanup()
        config.DB_PATH, database.DB_PATH, job_store.DB_PATH = self._old

    def _make_item(self, mode="full"):
        with patch.object(batches, "BilibiliCatalogClient", FakeCatalogClient):
            batch = batches.create_batch(
                self.creator_id, {"video_ids": [self.video_id]}, mode=mode, identity=IDENTITY,
            )
        item = batch["items"][0]
        job = job_store.get_job(item["job_id"], user_id=1)
        return batch, item, job

    async def test_cache_hit_reuses_without_ai(self):
        batch, item, job = self._make_item()
        with patch.object(batch_runner, "get_cached", return_value={"result_json": '{"result":{"summary":"摘要"},"notes":"笔记","mindmap_markdown":"# 导图","qa_pairs":[{"question":"问题","answer":"回答"}]}', "video_title": "旧"}):
            with patch.object(batch_runner, "generate_full_from_subtitle") as gen:
                result = await batch_runner.run_batch_item(job, self.scheduler)
        gen.assert_not_called()
        self.assertTrue(result["reused"])
        self.assertEqual("done", batches.get_batch(batch["id"], IDENTITY)["items"][0]["status"])

    async def test_fast_path_skips_parse_info(self):
        batch, item, job = self._make_item()

        def _fail_parse(url):
            raise AssertionError("快路径不应调用 parse_info")

        subtitle = ("字幕内容足够长。" * 20, "bilibili_cc", "zh")
        with patch.object(batch_runner, "get_cached", return_value=None):
            with patch.object(batch_runner, "save_video_info_cache"):
                with patch.object(batch_runner, "_parse_info", side_effect=_fail_parse):
                    with patch.object(batch_runner, "fetch_subtitle", return_value=subtitle):
                        with patch.object(batch_runner, "check_usage_limit_by_id", return_value=(True, 0, 20)):
                            with patch.object(batch_runner, "generate_full_from_subtitle",
                                              return_value={"result": {}, "notes": "n"}) as gen:
                                result = await batch_runner.run_batch_item(job, self.scheduler)

        self.assertEqual({"result", "notes"}, set(result["result_keys"]))
        _, kwargs = gen.call_args
        self.assertEqual("bilibili_cc", kwargs["subtitle_source"])
        self.assertIsNone(kwargs["raw_text"])

    async def test_whisper_path_uses_worker_subprocess(self):
        batch, item, job = self._make_item()

        def _parse(url):
            return SimpleNamespace(
                title="测试视频", webpage_url=url, id="BV1test", extractor="bilibili",
                description="", audio_stream_url="https://audio.example/a.m4s",
                parts=[SimpleNamespace(index=1, title="P1", cid=11, duration=60)],
                model_dump=lambda: {},
            )

        with patch.object(batch_runner, "get_cached", return_value=None):
            with patch.object(batch_runner, "save_video_info_cache"):
                with patch.object(batch_runner, "_parse_info", side_effect=_parse):
                    with patch.object(batch_runner, "fetch_subtitle", return_value=(None, "", "")):
                        with patch.object(batch_runner, "is_whisper_available", return_value=True):
                            with patch.object(batch_runner, "correct_subtitle_text",
                                              return_value="校正后的字幕" * 10):
                                with patch.object(batch_runner, "check_usage_limit_by_id",
                                                  return_value=(True, 0, 20)):
                                    with patch.object(batch_runner, "generate_full_from_subtitle",
                                                      return_value={"result": {}, "notes": "n"}) as gen:
                                        await batch_runner.run_batch_item(job, self.scheduler)

        self.assertEqual(1, len(self.scheduler.whisper_calls))
        _, kwargs = gen.call_args
        self.assertEqual("whisper", kwargs["subtitle_source"])
        self.assertIsNotNone(kwargs["raw_text"])

    async def test_whisper_unavailable_fails_clearly(self):
        batch, item, job = self._make_item()
        with patch.object(batch_runner, "get_cached", return_value=None):
            with patch.object(batch_runner, "save_video_info_cache"):
                with patch.object(batch_runner, "_parse_info",
                                  return_value=SimpleNamespace(
                                      title="t", webpage_url=job["url"], id="BV1test",
                                      extractor="bilibili", description="",
                                      parts=[SimpleNamespace(index=1, title="P1", cid=11, duration=60)])):
                    with patch.object(batch_runner, "fetch_subtitle", return_value=(None, "", "")):
                        with patch.object(batch_runner, "is_whisper_available", return_value=False):
                            with self.assertRaises(RuntimeError) as raised:
                                await batch_runner.run_batch_item(job, self.scheduler)
        self.assertIn("Whisper", str(raised.exception))

    async def test_usage_limit_skips_and_pauses_batch(self):
        batch, item, job = self._make_item()
        subtitle = ("字幕内容足够长。" * 20, "bilibili_cc", "zh")
        with patch.object(batch_runner, "get_cached", return_value=None):
            with patch.object(batch_runner, "save_video_info_cache"):
                with patch.object(batch_runner, "_parse_info",
                                  return_value=SimpleNamespace(
                                      title="t", webpage_url=job["url"], id="BV1test",
                                      extractor="bilibili", description="",
                                      parts=[SimpleNamespace(index=1, title="P1", cid=11, duration=60)])):
                    with patch.object(batch_runner, "fetch_subtitle", return_value=subtitle):
                        with patch.object(batch_runner, "check_usage_limit_by_id",
                                          return_value=(False, 20, 20)):
                            with patch.object(batch_runner, "generate_full_from_subtitle") as gen:
                                result = await batch_runner.run_batch_item(job, self.scheduler)
        gen.assert_not_called()
        self.assertEqual("usage_limit", result["skipped"])
        refreshed = batches.get_batch(batch["id"], IDENTITY)
        self.assertEqual("skipped", refreshed["items"][0]["status"])
        self.assertEqual("paused", refreshed["status"])

    async def test_meta_mode_stops_after_parse(self):
        batch, item, job = self._make_item(mode="meta")
        with patch.object(batch_runner, "get_cached", return_value=None):
            with patch.object(batch_runner, "save_video_info_cache"):
                with patch.object(batch_runner, "_parse_info",
                                  return_value=SimpleNamespace(
                                      title="t", webpage_url=job["url"], id="BV1test",
                                      extractor="bilibili", description="", parts=[])):
                    with patch.object(batch_runner, "fetch_subtitle") as fetch:
                        result = await batch_runner.run_batch_item(job, self.scheduler)
        fetch.assert_not_called()
        self.assertTrue(result["meta_only"])

    async def test_cancel_raises_job_cancelled(self):
        batch, item, job = self._make_item()
        job_store.update_job(job["task_id"], cancel_requested=1)
        job = job_store.get_job(job["task_id"], user_id=1)
        with patch.object(batch_runner, "get_cached", return_value=None):
            with self.assertRaises(JobCancelled):
                await batch_runner.run_batch_item(job, self.scheduler)


class HandlerDispatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (config.DB_PATH, database.DB_PATH, job_store.DB_PATH)
        config.DB_PATH = database.DB_PATH = job_store.DB_PATH = root / "knowledge.db"
        database.init_db()
        self.work_dir = root / "jobs"

    def tearDown(self):
        self.tmp.cleanup()
        config.DB_PATH, database.DB_PATH, job_store.DB_PATH = self._old

    async def test_handler_dispatch_marks_done(self):
        from core.job_scheduler import JobScheduler

        calls = []

        async def handler(job, scheduler):
            calls.append(job["task_id"])
            return {"ok": True}

        job_id = job_store.create_job("h1", "https://e.com/1", user_id=1,
                                      job_type="batch_item", payload={})
        terminal = []
        scheduler = JobScheduler(
            work_dir=self.work_dir,
            handlers={"batch_item": handler},
            on_terminal=lambda job, status, error=None: terminal.append(status),
        )
        await scheduler.run_once()
        self.assertEqual([job_id], calls)
        job = job_store.get_job(job_id, user_id=1)
        self.assertEqual("done", job["status"])
        self.assertEqual({"ok": True}, job["result"])
        self.assertEqual(["done"], terminal)

    async def test_handler_failure_marks_failed(self):
        from core.job_scheduler import JobScheduler

        async def handler(job, scheduler):
            raise RuntimeError("boom")

        job_id = job_store.create_job("h2", "https://e.com/2", user_id=1,
                                      job_type="batch_item", payload={})
        scheduler = JobScheduler(work_dir=self.work_dir, handlers={"batch_item": handler})
        await scheduler.run_once()
        job = job_store.get_job(job_id, user_id=1)
        self.assertEqual("failed", job["status"])
        self.assertIn("boom", job["error"])

    async def test_handler_cancel_marks_cancelled(self):
        from core.job_scheduler import JobScheduler

        async def handler(job, scheduler):
            raise JobCancelled()

        job_id = job_store.create_job("h3", "https://e.com/3", user_id=1,
                                      job_type="batch_item", payload={})
        scheduler = JobScheduler(work_dir=self.work_dir, handlers={"batch_item": handler})
        await scheduler.run_once()
        job = job_store.get_job(job_id, user_id=1)
        self.assertEqual("cancelled", job["status"])


if __name__ == "__main__":
    unittest.main()
