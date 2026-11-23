import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock

from fastapi import HTTPException
import database
from core import cache, job_store, learning
from core.models import VideoInfo
from core.pipeline import PipelineEvent
from core.job_scheduler import JobScheduler
from api import learning_routes

URL = "https://www.bilibili.com/video/BV1demotest"
TEXT = "[00:00] 这是一段用于验证独立学习资料生成的字幕。" * 8
OWNER = {"guest_id": "learning-test", "user_id": None}


class LearningWorkspaceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.db_patch = patch.object(database, "DB_PATH", root / "test.db")
        self.job_patch = patch.object(job_store, "DB_PATH", root / "test.db")
        self.db_patch.start()
        self.job_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.addCleanup(self.job_patch.stop)
        database.init_db()
        cache._ensure_table()
        cache._ensure_video_info_table()
        cache._ensure_whisper_table()
        self.info = VideoInfo(title="Test video", webpage_url=URL, duration=60, description="这是视频简介，足够长但不能代表整个视频的全文内容。", extractor="bilibili")
        cache.save_video_info_cache(URL, self.info)
        self.scheduler = JobScheduler(work_dir=root / "jobs", handlers={"learning": learning.run_learning_job})
        self.scheduler.work_dir.mkdir()

    def subtitle(self, url=URL):
        database.save_subtitle_to_db(url, "bilibili_cc", "zh", TEXT, "Test video", "bilibili",
                                    segments=[{"start": 0, "end": 3.5, "text": "第一句话"}])

    def job(self, targets, **extras):
        task_id = job_store.create_job(cache._url_hash(URL), URL, **OWNER,
                                        payload={"targets": targets, **extras}, job_type="learning")
        return job_store.get_job(task_id)

    async def test_invalid_cached_subtitle_is_hidden_and_refetched(self):
        database.save_subtitle_to_db(URL, 'bilibili_cc', 'zh', TEXT, segments=[{'start': 0, 'end': 9999, 'text': 'wrong'}])
        snapshot = learning.workspace(URL, OWNER)
        self.assertIsNone(snapshot['subtitle'])
        self.assertIn('时间轴', snapshot['subtitle_warning'])
        job = self.job([])
        with patch.object(learning, 'fetch_subtitle', new=AsyncMock(return_value=(TEXT, 'bilibili_cc', 'zh'))) as fetch:
            await self.scheduler.run_once()
        fetch.assert_awaited_once()
        self.assertEqual('done', job_store.get_job(job['task_id'])['status'])

    async def test_subtitle_provenance_roundtrip_and_mismatch(self):
        database.save_subtitle_to_db(URL, 'bilibili_cc', 'zh', TEXT, segments=[{'start': 0, 'end': 3, 'text': 'test'}],
                                    provenance={'version': 1, 'bvid': 'BVother', 'cid': '99'})
        stored = database.get_subtitle_from_db(URL)
        self.assertTrue(stored['provenance']['text_sha256'])
        self.assertTrue(stored['provenance']['fetched_at'])
        self.assertIsNone(learning.workspace(URL, OWNER)['subtitle'])

    def counts(self):
        with database.get_db() as conn:
            return (conn.execute("SELECT COUNT(*) FROM usage_logs WHERE status = 'SUCCESS'").fetchone()[0],
                    conn.execute("SELECT COUNT(*) FROM learning_usage WHERE status = 'reserved'").fetchone()[0])

    async def test_first_mindmap_does_not_generate_other_modules_and_preserves_segments(self):
        self.subtitle()
        job = self.job(["mindmap"])
        with patch.object(learning, "run_mindmap", return_value="# 导图\n- 第一节") as mindmap, patch.object(learning, "run_summary") as summary:
            await self.scheduler.run_once()
        self.assertEqual("done", job_store.get_job(job["task_id"])["status"])
        self.assertEqual(1, mindmap.call_count)
        summary.assert_not_called()
        snapshot = learning.workspace(URL, OWNER)
        self.assertEqual("missing", snapshot["modules"]["summary"]["status"])
        self.assertEqual("done", snapshot["modules"]["mindmap"]["status"])
        self.assertEqual(3.5, snapshot["subtitle"]["segments"][0]["end"])
        self.assertEqual((1, 0), self.counts())

    async def test_multiple_successes_charge_once_and_cache_only_is_free(self):
        self.subtitle()
        job = self.job(["summary", "mindmap"])
        with patch.object(learning, "run_summary", return_value=[PipelineEvent("result", {"summary": "有效摘要", "chapters": []})]), patch.object(learning, "run_mindmap", return_value="# 导图"):
            await self.scheduler.run_once()
        self.assertEqual((1, 0), self.counts())
        second = self.job(["summary", "mindmap"])
        self.assertNotEqual(job["task_id"], second["task_id"])
        with patch.object(learning, "run_summary") as summary, patch.object(learning, "run_mindmap") as mindmap:
            await self.scheduler.run_once()
        summary.assert_not_called()
        mindmap.assert_not_called()
        self.assertEqual((1, 0), self.counts())

    async def test_partial_failure_retains_success_and_does_not_commit_draft(self):
        self.subtitle()
        job = self.job(["summary", "notes", "mindmap"])
        with patch.object(learning, "run_summary", return_value=[PipelineEvent("warn", {"message": "model unavailable"})]), \
             patch.object(learning, "run_notes", return_value=[PipelineEvent("notes_text", {"text": "未完成草稿"}), PipelineEvent("warn", {"message": "中断"})]), \
             patch.object(learning, "run_mindmap", return_value="# 已完成的导图"):
            await self.scheduler.run_once()
        self.assertEqual("partial", job_store.get_job(job["task_id"])["status"])
        self.assertNotIn("notes", learning.payload_for(URL))
        self.assertIn("mindmap_markdown", learning.payload_for(URL))
        self.assertEqual((1, 0), self.counts())

    async def test_failed_regeneration_keeps_previous_and_is_not_billed(self):
        self.subtitle()
        first = self.job(["mindmap"])
        with patch.object(learning, "run_mindmap", return_value="# 原有导图"):
            await self.scheduler.run_once()
        self.job(["mindmap"], force=True)
        with patch.object(learning, "run_mindmap", return_value=""):
            await self.scheduler.run_once()
        self.assertEqual("# 原有导图", learning.payload_for(URL)["mindmap_markdown"])
        self.assertEqual((1, 0), self.counts())

    async def test_transcription_requires_confirmation_and_does_not_call_ai(self):
        job = self.job([])
        self.scheduler.run_worker_subprocess = AsyncMock(return_value={"subtitle_text": TEXT, "language": "zh", "segments": [{"start": 0, "end": 2.2, "text": "转录内容"}]})
        with patch.object(learning, "fetch_subtitle", new_callable=AsyncMock, return_value=(None, "", "")), patch.object(learning, "whisper_unavailable_reason", return_value=""):
            await self.scheduler.run_once()
            waiting = job_store.get_job(job["task_id"])
            self.assertEqual("awaiting_confirmation", waiting["status"])
            self.scheduler.run_worker_subprocess.assert_not_called()
            self.assertIsNone(job_store.claim_next_job())
            with patch.object(learning_routes, "require_identity", return_value=OWNER):
                await learning_routes.resume_task(job["task_id"], object())
            await self.scheduler.run_once()
        self.assertEqual("done", job_store.get_job(job["task_id"])["status"])
        self.assertEqual(2.2, learning.workspace(URL, OWNER)["subtitle"]["segments"][0]["end"])
        self.assertEqual((0, 0), self.counts())

    async def test_temporary_subtitle_failure_offers_transcription_without_automatic_start(self):
        from core.pipeline.subtitle import BilibiliSubtitleUnavailable
        job = self.job([])
        self.scheduler.run_worker_subprocess = AsyncMock(return_value={"subtitle_text": TEXT})
        with patch.object(learning, "fetch_subtitle", new_callable=AsyncMock, side_effect=BilibiliSubtitleUnavailable("暂时不可用")) as fetch, patch.object(learning, "whisper_unavailable_reason", return_value=""):
            await self.scheduler.run_once()
            waiting = job_store.get_job(job["task_id"])
            self.assertEqual("awaiting_confirmation", waiting["status"])
            self.assertIn("暂未取到", waiting["message"])
            self.scheduler.run_worker_subprocess.assert_not_called()
            with patch.object(learning_routes, "require_identity", return_value=OWNER):
                await learning_routes.resume_task(job["task_id"], object())
            await self.scheduler.run_once()
        fetch.assert_awaited_once()
        self.assertEqual("done", job_store.get_job(job["task_id"])["status"])

    async def test_bilibili_access_block_offers_description_when_no_audio_is_available(self):
        from core.bilibili_guard import BilibiliAccessBlocked
        job = self.job([])
        self.scheduler.run_worker_subprocess = AsyncMock()
        with patch.object(learning, "fetch_subtitle", new_callable=AsyncMock,
                          side_effect=BilibiliAccessBlocked("B 站视频解析暂时受限（HTTP 412）")):
            await self.scheduler.run_once()
        failed = job_store.get_job(job["task_id"])
        self.assertEqual("failed", failed["status"])
        self.assertIn("HTTP 412", failed["error"])
        self.assertTrue(failed["result"]["subtitle_unavailable"])
        self.scheduler.run_worker_subprocess.assert_not_called()

    async def test_confirmed_refresh_retranscribes_instead_of_reusing_old_whisper(self):
        database.save_subtitle_to_db(URL, "whisper", "zh", TEXT)
        job = self.job([], refresh_subtitle=True, allow_transcription=True)
        new_text = TEXT + "新识别的内容"
        self.scheduler.run_worker_subprocess = AsyncMock(return_value={"subtitle_text": new_text})
        with patch.object(learning, "whisper_unavailable_reason", return_value=""):
            await self.scheduler.run_once()
        self.scheduler.run_worker_subprocess.assert_awaited_once()
        self.assertEqual("done", job_store.get_job(job["task_id"])["status"])
        self.assertEqual(new_text, database.get_subtitle_from_db(URL)["full_text"])

    async def test_restart_skips_committed_module_and_does_not_charge_twice(self):
        self.subtitle()
        job = self.job(["summary", "mindmap"])
        job_store.claim_next_job()
        learning.reserve_usage(job)
        learning.save_artifact(job, self.info, TEXT, "bilibili_cc", "zh", "summary", {"summary": "已保存摘要"})
        job_store.recover_interrupted_jobs()
        with patch.object(learning, "run_summary") as summary, patch.object(learning, "run_mindmap", return_value="# 导图"):
            await self.scheduler.run_once()
        summary.assert_not_called()
        self.assertEqual((1, 0), self.counts())

    async def test_cancelled_awaiting_job_releases_reservation_and_slot(self):
        job = self.job(["summary"])
        learning.reserve_usage(job)
        job_store.update_job(job["task_id"], status="awaiting_confirmation")
        from api import task_routes
        with patch.object(task_routes, "require_identity", return_value=OWNER):
            await task_routes.cancel_task(job["task_id"], object())
        self.assertEqual((0, 0), self.counts())
        self.assertEqual("cancelled", job_store.get_job(job["task_id"])["status"])

    async def test_description_summary_is_distinct_and_does_not_mark_full_summary_ready(self):
        job = self.job(["summary"], input_source="description")
        with patch("core.summarizer.summarize_from_description", return_value={"summary": "简介摘要"}):
            await self.scheduler.run_once()
        snapshot = learning.workspace(URL, OWNER)
        self.assertIn("description_summary", snapshot["artifacts"])
        self.assertEqual("missing", snapshot["modules"]["summary"]["status"])
        self.assertIsNone(snapshot["subtitle"])

    def test_idempotency_and_conflicting_targets(self):
        with patch.object(learning_routes, "is_ai_available", return_value=True):
            first = learning_routes.submit(learning_routes.GenerateRequest(url=URL, targets=["summary"], request_key="one"), OWNER, ["summary"])
            second = learning_routes.submit(learning_routes.GenerateRequest(url=URL, targets=["summary"], request_key="one"), OWNER, ["summary"])
            self.assertEqual(first["task_id"], second["task_id"])
            with self.assertRaises(HTTPException) as raised:
                learning_routes.submit(learning_routes.GenerateRequest(url=URL, targets=["notes"], request_key="two"), OWNER, ["notes"])
            self.assertEqual(409, raised.exception.status_code)
        self.assertEqual((0, 1), self.counts())

    def test_quota_reservations_block_parallel_admission(self):
        first = self.job(["summary"])
        with patch("core.auth.GUEST_DAILY_LIMIT", 1):
            learning.reserve_usage(first)
            with self.assertRaises(ValueError):
                learning.reserve_usage({**OWNER, "task_id": "other"})
        learning.release_usage(first["task_id"])
        self.assertEqual((0, 0), self.counts())

    def test_subtitle_change_invalidates_modules_independently_and_parts_are_separate(self):
        self.subtitle()
        job = self.job(["mindmap"])
        learning.reserve_usage(job)
        learning.save_artifact(job, self.info, TEXT, "bilibili_cc", "zh", "mindmap", "# 导图")
        database.save_subtitle_to_db(URL, "bilibili_cc", "zh", "修改后的字幕内容")
        self.assertTrue(learning.workspace(URL, OWNER)["modules"]["mindmap"]["stale"])
        self.assertEqual({}, learning.workspace(URL + "?p=2", OWNER)["artifacts"])

    async def test_task_events_and_resume_are_owner_scoped(self):
        job = self.job([])
        job_store.update_job(job["task_id"], status="awaiting_confirmation")
        with patch.object(learning_routes, "require_identity", return_value={"guest_id": "other"}):
            with self.assertRaises(HTTPException) as raised:
                await learning_routes.resume_task(job["task_id"], object())
            self.assertEqual(404, raised.exception.status_code)

    def test_event_replay_has_stable_cursor(self):
        job = self.job([])
        learning.emit(job["task_id"], "progress", {"message": "first"})
        first = learning.events_after(job["task_id"])
        learning.emit(job["task_id"], "progress", {"message": "second"})
        second = learning.events_after(job["task_id"], first[-1]["id"])
        self.assertEqual(1, len(second))
        self.assertEqual("second", json.loads(second[0]["event_json"])["data"]["message"])

    async def test_subtitle_event_wakes_stream_without_polling_delay(self):
        job = self.job([])
        stream = learning_routes.event_stream(job["task_id"], OWNER)
        try:
            self.assertIn(b"task_progress", await anext(stream))
            self.assertIn(b"heartbeat", await anext(stream))
            next_event = asyncio.create_task(anext(stream))
            await asyncio.to_thread(learning.emit, job["task_id"], "subtitle_ready", {})
            self.assertIn(b"subtitle_ready", await asyncio.wait_for(next_event, 0.4))
        finally:
            await stream.aclose()

    async def test_terminal_transition_during_event_read_does_not_drop_last_event(self):
        job = self.job([])
        original = learning.events_after
        injected = False

        def read_then_finish(task_id, after):
            nonlocal injected
            rows = original(task_id, after)
            if not injected:
                injected = True
                learning.emit(task_id, "subtitle_ready", {})
                job_store.update_job(task_id, status="done")
            return rows

        async def collect():
            with patch.object(learning, "events_after", side_effect=read_then_finish):
                return [frame async for frame in learning_routes.event_stream(job["task_id"], OWNER)]

        frames = await asyncio.wait_for(collect(), 0.4)
        self.assertTrue(any(b"subtitle_ready" in frame for frame in frames))
        self.assertIn(b"task_state", frames[-1])

    async def test_stream_checks_owner_before_reading_events(self):
        job = self.job([])
        learning.emit(job["task_id"], "subtitle_ready", {})
        frames = [frame async for frame in learning_routes.event_stream(job["task_id"], {"guest_id": "other"})]
        self.assertEqual([], frames)

    def test_submit_waits_for_initialization_before_admitting_job(self):
        with patch.object(learning_routes, "normalize", return_value=URL), \
                patch.object(learning, "restore_subtitle") as restore:
            restore.side_effect = lambda *args: self.assertIsNone(job_store.claim_next_job())
            job = learning_routes.submit(learning_routes.PrepareRequest(url=URL), OWNER, [])
        self.assertNotIn("_admission_pending", job["payload"])
        self.assertEqual(job["task_id"], job_store.claim_next_job()["task_id"])

    def test_failed_submit_releases_reservation_and_cannot_run(self):
        with patch.object(learning_routes, "normalize", return_value=URL), \
                patch.object(learning_routes, "is_ai_available", return_value=True), \
                patch.object(learning, "restore_subtitle", side_effect=RuntimeError("initialization failed")):
            with self.assertRaisesRegex(RuntimeError, "initialization failed"):
                learning_routes.submit(learning_routes.GenerateRequest(url=URL, targets=["summary"]), OWNER, ["summary"])
        self.assertEqual((0, 0), self.counts())
        self.assertIsNone(job_store.claim_next_job())
        with database.get_db() as conn:
            self.assertEqual("failed", conn.execute("SELECT status FROM background_jobs").fetchone()[0])

    def test_duplicate_submit_cannot_admit_pending_job(self):
        pending = self.job([], request_key="same", refresh_subtitle=False,
                           _admission_pending=True, _admission_token="first")
        with patch.object(learning_routes, "normalize", return_value=URL):
            duplicate = learning_routes.submit(learning_routes.PrepareRequest(url=URL, request_key="same"), OWNER, [])
        self.assertEqual(pending["task_id"], duplicate["task_id"])
        self.assertTrue(duplicate["payload"]["_admission_pending"])
        self.assertIsNone(job_store.claim_next_job())

    async def test_submit_to_subtitle_event_while_generation_is_running(self):
        heavy_started, release = asyncio.Event(), asyncio.Event()
        heavy_id = job_store.create_job("other-video", "https://example.com/other", **OWNER,
                                        payload={"targets": ["summary"]}, job_type="learning")

        async def long_handler(job, scheduler):
            heavy_started.set()
            await release.wait()
            return {}

        long = JobScheduler(lane="default", work_dir=self.scheduler.work_dir,
                            handlers={"learning": long_handler})
        native = JobScheduler(lane="subtitle", work_dir=self.scheduler.work_dir, poll_interval=30,
                              handlers={"learning": learning.run_learning_job})
        with patch.object(learning, "fetch_subtitle", new=AsyncMock(return_value=(TEXT, "bilibili_cc", "zh"))), \
                patch.object(learning_routes, "normalize", return_value=URL):
            await long.start()
            await native.start(recover_interrupted=False)
            try:
                await asyncio.wait_for(heavy_started.wait(), 1)
                started = time.monotonic()
                job = await asyncio.to_thread(learning_routes.submit,
                                              learning_routes.PrepareRequest(url=URL), OWNER, [])
                stream = learning_routes.event_stream(job["task_id"], OWNER)

                async def until_ready():
                    async for frame in stream:
                        if b'"subtitle_ready"' in frame:
                            return
                    self.fail("subtitle event missing")

                try:
                    await asyncio.wait_for(until_ready(), 0.5)
                    elapsed_ms = (time.monotonic() - started) * 1000
                    self.assertIsNotNone(learning.workspace(URL, OWNER)["subtitle"])
                    self.assertEqual("downloading", job_store.get_job(heavy_id)["status"])
                    print(f"submit_to_subtitle_ready_ms={elapsed_ms:.1f} (mock upstream; long task still running)")
                finally:
                    await stream.aclose()
            finally:
                release.set()
                await asyncio.gather(long.stop(), native.stop())
