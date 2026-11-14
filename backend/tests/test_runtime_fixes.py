"""Regressions for quota cleanup, durable learning data and nonblocking parsing."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import database
from api import routes, stream_routes
from core import cache, job_store, learning
from core.models import ParseRequest, VideoInfo
from core.pipeline import PipelineEvent
from core.summary_models import ChatRequest, QaGenerationRequest


URL = "https://example.test/video"
OWNER = {"user_id": None, "guest_id": "quota-regression"}


class RuntimeFixTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        path = Path(self.tmp.name) / "test.db"
        self.stack.enter_context(patch.object(database, "DB_PATH", path))
        self.stack.enter_context(patch.object(job_store, "DB_PATH", path))
        database.init_db()
        cache._ensure_table()
        self.stack.enter_context(patch.object(stream_routes, "is_ai_available", return_value=True))
        self.stack.enter_context(patch.object(stream_routes, "require_identity", return_value=OWNER))
        self.stack.enter_context(patch.object(stream_routes, "check_usage_limit", return_value=(True, 0, 20)))

    async def consume(self, response):
        return b"".join([chunk async for chunk in response.body_iterator])

    def counts(self):
        with database.get_db() as conn:
            return (
                conn.execute("SELECT COUNT(*) FROM learning_usage WHERE status='reserved'").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM usage_logs WHERE status='SUCCESS'").fetchone()[0],
            )

    async def test_chat_success_is_billed_once_and_releases_reservation(self):
        with patch.object(stream_routes, "stream_chat", return_value=iter([("text", "answer")])):
            response = await stream_routes.chat_stream(ChatRequest(subtitle_text="字幕内容" * 10, question="问题"), object())
            body = await self.consume(response)
        self.assertNotIn(b'"type": "error"', body)
        self.assertEqual((0, 1), self.counts())

    async def test_chat_error_releases_quota_without_billing(self):
        with patch.object(stream_routes, "stream_chat", return_value=iter([("error", {"message": "unavailable"})])):
            response = await stream_routes.chat_stream(ChatRequest(subtitle_text="字幕内容" * 10, question="问题"), object())
            await self.consume(response)
        self.assertEqual((0, 0), self.counts())

    async def test_text_qa_success_and_failure_release_reservations(self):
        for events, billed in (
            ([PipelineEvent("qa_pairs", [{"question": "Q", "answer": "A"}])], 1),
            ([], 1),
        ):
            with patch.object(stream_routes, "run_qanda", return_value=iter(events)):
                response = await stream_routes.qa_stream(QaGenerationRequest(subtitle_text="字幕" * 20), object())
                await self.consume(response)
            self.assertEqual((0, billed), self.counts())

    async def test_disconnected_chat_releases_reservation(self):
        def interrupted_stream(*_args):
            yield "text", "partial"
            yield "text", "unfinished"

        # Close the stream at the same generator boundary used on disconnect.
        async def close_early(generator):
            next(generator)
            generator.close()
            yield b"closed"

        with patch.object(stream_routes, "stream_chat", side_effect=interrupted_stream), patch.object(stream_routes, "_sse_generator", side_effect=close_early):
            response = await stream_routes.chat_stream(ChatRequest(subtitle_text="字幕内容" * 10, question="问题"), object())
            await self.consume(response)
        self.assertEqual((0, 0), self.counts())

    def test_startup_clears_abandoned_reservations_but_keeps_resumable_jobs(self):
        active = job_store.create_job(cache._url_hash(URL), URL, **OWNER, job_type="learning")
        job_store.update_job(active, status="awaiting_confirmation")
        with database.get_db() as conn:
            conn.executemany("INSERT INTO learning_usage(operation_id, guest_id, status) VALUES (?, ?, ?)", [
                ("chat-abandoned", OWNER["guest_id"], "reserved"),
                ("qanda-abandoned", OWNER["guest_id"], "reserved"),
                (active, OWNER["guest_id"], "reserved"),
                ("charged-operation", OWNER["guest_id"], "charged"),
            ])
        learning.recover_usage_reservations()
        with database.get_db() as conn:
            remaining = {r[0] for r in conn.execute("SELECT operation_id FROM learning_usage")}
        self.assertEqual({active, "charged-operation"}, remaining)

    def test_retention_preserves_saved_artifacts_and_transcripts_for_every_identity(self):
        for fingerprinted in (False, True):
            with self.subTest(fingerprinted=fingerprinted):
                suffix = str(fingerprinted)
                old = f"{URL}/saved-{suffix}"
                orphan = f"{URL}/orphan-{suffix}"
                favorite = f"{URL}/favorite-{suffix}"
                with patch.object(cache, "AI_CACHE_KEEP", 1):
                    for url in (old, orphan, favorite):
                        cache.save_cache(url, subtitle_text="transcript", result_json='{"result":{"summary":"saved"}}',
                                         fingerprint=url if fingerprinted else None)
                        database.save_subtitle_to_db(url, "platform", "zh", "transcript", "Title")
                        with database.get_db() as conn:
                            conn.execute("UPDATE ai_cache SET updated_at='2000-01-01' WHERE url_hash=?", (cache._url_hash(url),))
                            if url == old:
                                conn.execute("INSERT INTO user_history(guest_id,url_hash,url) VALUES ('another-owner',?,?)", (cache._url_hash(url), url))
                            if url == favorite:
                                conn.execute("UPDATE ai_cache SET is_favorite=1 WHERE url_hash=?", (cache._url_hash(url),))
                    job = job_store.create_job(cache._url_hash(orphan), orphan, **OWNER)
                    job_store.update_job(job, status="done")
                    learning.emit(job, "finished", {})
                    with database.get_db() as conn:
                        video_id = conn.execute("SELECT id FROM videos WHERE url=?", (orphan,)).fetchone()[0]
                        tag_id = conn.execute("INSERT INTO tags(name) VALUES (?)", (suffix,)).lastrowid
                        conn.execute("INSERT INTO video_tags(video_id,tag_id) VALUES (?,?)", (video_id, tag_id))
                    cache.save_cache(f"{URL}/new-{suffix}", result_json='{"result":{"summary":"new"}}',
                                     fingerprint=f"new-{suffix}" if fingerprinted else None)
                    self.assertIsNotNone(cache._get_cached_raw(old))
                    self.assertIsNotNone(cache._get_cached_raw(favorite))
                    self.assertIsNone(cache._get_cached_raw(orphan))
                    for url in (old, orphan, favorite):
                        self.assertEqual("transcript", database.get_subtitle_from_db(url)["full_text"])
                    with database.get_db() as conn:
                        self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM video_tags WHERE video_id=?", (video_id,)).fetchone()[0])
                        self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM learning_events WHERE task_id=?", (job,)).fetchone()[0])

    async def test_parse_and_refresh_leave_event_loop_responsive(self):
        loop_thread = threading.get_ident()
        seen_threads = []
        started = threading.Event()
        release = threading.Event()

        def block(*args, **kwargs):
            seen_threads.append(threading.get_ident())
            started.set()
            release.wait(timeout=1)
            return VideoInfo(title="Demo", webpage_url=URL)

        with ExitStack() as stack:
            stack.enter_context(patch.object(routes, "require_identity", return_value=OWNER))
            stack.enter_context(patch.object(routes, "extract_url", return_value=URL))
            stack.enter_context(patch.object(routes, "ensure_public_http_url"))
            stack.enter_context(patch.object(routes.downloader, "parse_info", side_effect=block))
            stack.enter_context(patch.object(routes, "save_video_info_cache"))
            stack.enter_context(patch.object(routes, "get_learned_part_indexes", return_value=set()))
            stack.enter_context(patch.object(routes, "get_part_coverage", return_value={}))
            task = asyncio.create_task(routes.parse_video(ParseRequest(url=URL), object()))
            try:
                for _ in range(50):
                    if started.is_set():
                        break
                    await asyncio.sleep(0.01)
                self.assertTrue(started.is_set())
                self.assertFalse(task.done(), "synchronous extraction blocked the event loop")
            finally:
                release.set()
                await task
            self.assertNotEqual(loop_thread, seen_threads[0])

            def refresh(*args, **kwargs):
                seen_threads.append(threading.get_ident())
                return {"formats": [{"url": "https://cdn.test/stream", "vcodec": "h264", "acodec": "aac", "height": 720}]}

            with patch("yt_dlp.YoutubeDL") as ydl:
                ydl.return_value.__enter__.return_value.extract_info.side_effect = refresh
                result = await routes.refresh_stream_url(URL, object())
            self.assertEqual("https://cdn.test/stream", result["stream_url"])
            self.assertNotEqual(loop_thread, seen_threads[-1])

    async def test_parse_preserves_auth_failure_status(self):
        with patch.object(routes, "require_identity", side_effect=HTTPException(403, "need login")):
            with self.assertRaises(HTTPException) as raised:
                await routes.parse_video(ParseRequest(url=URL), object())
        self.assertEqual(403, raised.exception.status_code)

    def test_download_directory_uses_environment_configuration(self):
        output = str(Path(self.tmp.name) / "custom-downloads")
        backend = str(Path(__file__).resolve().parents[1])
        result = subprocess.run([sys.executable, "-B", "-c",
            "import json; from api.routes import downloader; print(json.dumps(downloader.output_dir))"],
            env={**os.environ, "PYTHONPATH": backend, "DOWNLOAD_DIR": output},
            capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(output, json.loads(result.stdout.strip().splitlines()[-1]))
        self.assertTrue(Path(output).is_dir())
