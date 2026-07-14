import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import database
from api import stream_routes
from core import cache
from core.models import VideoInfo
from core.pipeline import PipelineEvent
from core.summary_models import QaGenerationRequest, SummarizeRequest


URL = "https://www.example.com/video/demo"
OLD_CACHE = {
    "url": URL,
    "video_title": "Old title",
    "subtitle_text": "Old subtitle text that must remain available to every user.",
    "source": "old-source",
    "result_json": json.dumps({"result": {"summary": "Old shared summary"}}),
    "part_info": "",
    "platform": "example",
}


async def consume_stream(response) -> bytes:
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


class StreamingGenerateThenSwapTests(unittest.IsolatedAsyncioTestCase):
    def _patch_full_pipeline(self, stack: ExitStack, info: VideoInfo, summary_events: list):
        stack.enter_context(patch.object(stream_routes, "is_ai_available", return_value=True))
        stack.enter_context(patch.object(stream_routes, "extract_url", return_value=URL))
        stack.enter_context(patch.object(stream_routes, "ensure_public_http_url"))
        stack.enter_context(
            patch.object(
                stream_routes,
                "require_identity",
                return_value={"user_id": 7, "guest_id": None, "guest_sig": None},
            )
        )
        stack.enter_context(patch.object(stream_routes, "get_cached", return_value=OLD_CACHE))
        delete_cache = stack.enter_context(
            patch.object(stream_routes, "delete_cache", create=True)
        )
        stack.enter_context(
            patch.object(stream_routes, "check_usage_limit", return_value=(True, 0, 20))
        )
        stack.enter_context(patch.object(stream_routes, "get_video_info_cache", return_value=None))
        stack.enter_context(patch.object(stream_routes, "find_active_job", return_value=None))
        stack.enter_context(
            patch.object(stream_routes, "_quick_db_subtitle_check", return_value=True)
        )
        stack.enter_context(patch.object(stream_routes.downloader, "parse_info", return_value=info))
        save_video_info = stack.enter_context(
            patch.object(stream_routes, "save_video_info_cache", create=True)
        )
        stack.enter_context(patch.object(stream_routes, "_quick_subtitle_check", return_value=True))
        stack.enter_context(
            patch.object(
                stream_routes,
                "fetch_subtitle",
                return_value=("New subtitle text long enough for generation.", "native", "zh"),
            )
        )
        save_subtitle = stack.enter_context(
            patch.object(stream_routes, "save_subtitle", create=True)
        )
        stack.enter_context(
            patch.object(stream_routes, "run_summary", return_value=summary_events)
        )
        stack.enter_context(patch.object(stream_routes, "run_mindmap", return_value=""))
        stack.enter_context(patch.object(stream_routes, "run_notes", return_value=[]))
        stack.enter_context(patch.object(stream_routes, "run_qanda", return_value=[]))
        stack.enter_context(patch.object(stream_routes, "run_tags"))
        save_cache = stack.enter_context(
            patch.object(stream_routes, "save_cache", create=True)
        )
        log_usage = stack.enter_context(patch.object(stream_routes, "log_usage"))
        commit_full_generation = stack.enter_context(
            patch.object(stream_routes, "commit_full_generation", create=True)
        )
        return {
            "delete_cache": delete_cache,
            "save_video_info": save_video_info,
            "save_subtitle": save_subtitle,
            "save_cache": save_cache,
            "log_usage": log_usage,
            "commit_full_generation": commit_full_generation,
        }

    async def test_force_failure_never_predeletes_shared_cache(self):
        with (
            patch.object(stream_routes, "is_ai_available", return_value=True),
            patch.object(stream_routes, "extract_url", return_value=URL),
            patch.object(stream_routes, "ensure_public_http_url"),
            patch.object(
                stream_routes,
                "require_identity",
                return_value={"user_id": 7, "guest_id": None, "guest_sig": None},
            ),
            patch.object(stream_routes, "get_cached", return_value=OLD_CACHE),
            patch.object(stream_routes, "delete_cache", create=True) as delete_cache,
            patch.object(stream_routes, "check_usage_limit", return_value=(True, 0, 20)),
            patch.object(
                stream_routes,
                "get_video_info_cache",
                side_effect=RuntimeError("metadata lookup failed"),
            ),
        ):
            with self.assertRaises(HTTPException):
                await stream_routes.summarize_stream(
                    SummarizeRequest(url=URL, force=True),
                    object(),
                )

        delete_cache.assert_not_called()

    async def test_empty_forced_summary_preserves_all_existing_records_and_usage(self):
        info = VideoInfo(title="New title", webpage_url=URL, duration=60)
        with ExitStack() as stack:
            mocks = self._patch_full_pipeline(
                stack,
                info,
                [PipelineEvent("warn", {"message": "empty summary"})],
            )
            response = await stream_routes.summarize_stream(
                SummarizeRequest(url=URL, force=True),
                object(),
            )
            body = await consume_stream(response)

        self.assertIn(b'"type": "error"', body)
        mocks["delete_cache"].assert_not_called()
        mocks["save_video_info"].assert_not_called()
        mocks["save_subtitle"].assert_not_called()
        mocks["save_cache"].assert_not_called()
        mocks["commit_full_generation"].assert_not_called()
        mocks["log_usage"].assert_not_called()

    async def test_successful_full_generation_commits_once_after_validation(self):
        info = VideoInfo(title="New title", webpage_url=URL, duration=60)
        result = {"summary": "Validated new summary", "chapters": []}
        with ExitStack() as stack:
            mocks = self._patch_full_pipeline(
                stack,
                info,
                [PipelineEvent("result", result)],
            )
            response = await stream_routes.summarize_stream(
                SummarizeRequest(url=URL, force=True),
                object(),
            )
            body = await consume_stream(response)

        self.assertIn(b'"type": "done"', body)
        mocks["commit_full_generation"].assert_called_once()
        mocks["delete_cache"].assert_not_called()
        mocks["save_video_info"].assert_not_called()
        mocks["save_subtitle"].assert_not_called()
        mocks["save_cache"].assert_not_called()
        mocks["log_usage"].assert_not_called()

    async def test_subtitle_regeneration_does_not_delete_previous_whisper_cache(self):
        cached_info = {"title": "Old title", "duration": 60, "fingerprint": "demo:1"}
        job = {
            "task_id": "job-1",
            "url_hash": "hash-1",
            "estimated_seconds": 10,
            "queue_position": 1,
        }
        with (
            patch.object(stream_routes, "is_whisper_available", return_value=True),
            patch.object(stream_routes, "get_video_info_cache", return_value=cached_info),
            patch.object(
                stream_routes,
                "delete_whisper_cache",
                create=True,
            ) as delete_whisper_cache,
            patch.object(stream_routes, "enqueue_whisper_job", return_value=job),
        ):
            response = await stream_routes._partial_subtitle(
                SummarizeRequest(url=URL, force=True, mode="subtitle"),
                OLD_CACHE,
                {"user_id": 7, "guest_id": None},
                URL,
                "trace",
            )

        self.assertEqual(200, response.status_code)
        delete_whisper_cache.assert_not_called()

    async def test_empty_partial_summary_keeps_previous_cache_and_quota(self):
        with (
            patch.object(
                stream_routes,
                "get_video_info_cache",
                return_value={"title": "Old title", "fingerprint": "demo:1"},
            ),
            patch.object(
                stream_routes,
                "run_summary",
                return_value=[PipelineEvent("warn", {"message": "empty summary"})],
            ),
            patch.object(stream_routes, "save_cache", create=True) as save_cache,
            patch.object(stream_routes, "log_usage") as log_usage,
        ):
            response = await stream_routes._handle_partial(
                SummarizeRequest(url=URL, force=True, mode="summary"),
                OLD_CACHE,
                {"user_id": 7, "guest_id": None},
                URL,
                "trace",
            )
            body = await consume_stream(response)

        self.assertIn(b'"type": "error"', body)
        save_cache.assert_not_called()
        log_usage.assert_not_called()

    async def test_partial_failure_does_not_prewrite_parsed_video_metadata(self):
        info = VideoInfo(title="Parsed title", webpage_url=URL, duration=60)
        with (
            patch.object(stream_routes, "get_video_info_cache", return_value=None),
            patch.object(stream_routes.downloader, "parse_info", return_value=info),
            patch.object(stream_routes, "save_video_info_cache", create=True) as save_video_info,
            patch.object(
                stream_routes,
                "run_summary",
                return_value=[PipelineEvent("warn", {"message": "empty summary"})],
            ),
        ):
            response = await stream_routes._handle_partial(
                SummarizeRequest(url=URL, force=True, mode="summary"),
                OLD_CACHE,
                {"user_id": 7, "guest_id": None},
                URL,
                "trace",
            )
            body = await consume_stream(response)

        self.assertIn(b'"type": "error"', body)
        save_video_info.assert_not_called()

    async def test_subtitle_job_queueing_does_not_prewrite_video_metadata(self):
        info = VideoInfo(title="Parsed title", webpage_url=URL, duration=60)
        job = {
            "task_id": "job-2",
            "url_hash": "hash-2",
            "estimated_seconds": 10,
            "queue_position": 1,
        }
        with (
            patch.object(stream_routes, "is_whisper_available", return_value=True),
            patch.object(stream_routes, "get_video_info_cache", return_value=None),
            patch.object(stream_routes.downloader, "parse_info", return_value=info),
            patch.object(stream_routes, "save_video_info_cache", create=True) as save_video_info,
            patch.object(stream_routes, "enqueue_whisper_job", return_value=job),
        ):
            response = await stream_routes._partial_subtitle(
                SummarizeRequest(url=URL, force=True, mode="subtitle"),
                OLD_CACHE,
                {"user_id": 7, "guest_id": None},
                URL,
                "trace",
            )

        self.assertEqual(200, response.status_code)
        save_video_info.assert_not_called()

    async def test_empty_description_fallback_does_not_log_success(self):
        info = VideoInfo(
            title="No subtitle video",
            webpage_url=URL,
            description="A sufficiently long description for the fallback path.",
        )
        with (
            patch.object(stream_routes, "summarize_from_description", return_value={}),
            patch.object(stream_routes, "log_usage") as log_usage,
        ):
            response = stream_routes._handle_no_subtitle(
                info,
                {"user_id": 7, "guest_id": None},
            )
            body = await consume_stream(response)

        self.assertIn(b'"type": "error"', body)
        log_usage.assert_not_called()

    async def test_empty_qanda_result_keeps_cache_and_quota(self):
        with (
            patch.object(stream_routes, "is_ai_available", return_value=True),
            patch.object(
                stream_routes,
                "require_identity",
                return_value={"user_id": 7, "guest_id": None, "guest_sig": None},
            ),
            patch.object(stream_routes, "check_usage_limit", return_value=(True, 0, 20)),
            patch.object(
                stream_routes,
                "run_qanda",
                return_value=[PipelineEvent("warn", {"message": "empty qanda"})],
            ),
            patch.object(stream_routes, "_merge_and_save_qanda") as merge_qanda,
            patch.object(stream_routes, "log_usage") as log_usage,
        ):
            response = await stream_routes.qa_stream(
                QaGenerationRequest(
                    subtitle_text="Subtitle text long enough for qanda.",
                    video_title="Demo",
                    url=URL,
                    force=True,
                ),
                object(),
            )
            body = await consume_stream(response)

        self.assertIn(b'"type": "error"', body)
        merge_qanda.assert_not_called()
        log_usage.assert_not_called()


class LegacySummaryValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_summary_does_not_prewrite_metadata_or_usage(self):
        from api import summary_routes

        info = VideoInfo(title="Parsed title", webpage_url=URL, duration=60)
        with (
            patch.object(summary_routes, "is_ai_available", return_value=True),
            patch.object(
                summary_routes,
                "require_identity",
                return_value={"user_id": 7, "guest_id": None, "guest_sig": None},
            ),
            patch.object(summary_routes, "check_usage_limit", return_value=(True, 0, 20)),
            patch.object(summary_routes, "extract_url", return_value=URL),
            patch.object(summary_routes, "ensure_public_http_url"),
            patch.object(summary_routes, "get_video_info_cache", return_value=None),
            patch.object(summary_routes.downloader, "parse_info", return_value=info),
            patch.object(summary_routes, "save_video_info_cache", create=True) as save_video_info,
            patch.object(
                summary_routes,
                "fetch_subtitle",
                return_value=("Subtitle text long enough for summary generation." * 2, "native", "zh"),
            ),
            patch.object(summary_routes, "summarize_subtitle", return_value={}),
            patch.object(summary_routes, "log_usage") as log_usage,
        ):
            with self.assertRaises(HTTPException):
                await summary_routes.summarize_video(
                    SummarizeRequest(url=URL),
                    object(),
                )

        save_video_info.assert_not_called()
        log_usage.assert_not_called()


class BackgroundGenerateThenSwapTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_background_summary_writes_nothing_and_raises(self):
        from core import background_pipeline

        info = VideoInfo(title="New title", webpage_url=URL, id="demo", extractor="example")
        job = {
            "task_id": "job-full",
            "url": URL,
            "user_id": 7,
            "guest_id": None,
            "lang": "zh",
            "payload": {"pipeline": "full"},
        }
        worker_result = {
            "subtitle_text": "Raw transcript text long enough to pass validation.",
            "language": "zh",
        }

        with (
            patch.object(background_pipeline, "_load_video_info", AsyncMock(return_value=info)),
            patch.object(background_pipeline, "save_video_info_cache", create=True) as save_video_info,
            patch.object(
                background_pipeline,
                "correct_subtitle_text",
                AsyncMock(return_value="Corrected transcript text long enough to pass validation."),
            ),
            patch.object(background_pipeline, "save_whisper_cache", create=True) as save_whisper_cache,
            patch.object(background_pipeline, "save_subtitle", create=True) as save_subtitle,
            patch.object(
                background_pipeline,
                "run_summary",
                return_value=[PipelineEvent("warn", {"message": "empty summary"})],
            ),
            patch.object(background_pipeline, "run_mindmap", return_value=""),
            patch.object(background_pipeline, "run_notes", return_value=[]),
            patch.object(background_pipeline, "run_qanda", return_value=[]),
            patch.object(background_pipeline, "save_cache", create=True) as save_cache,
            patch.object(background_pipeline, "log_usage", create=True) as log_usage,
            patch.object(background_pipeline.job_store, "update_job"),
        ):
            with self.assertRaises(ValueError):
                await background_pipeline.finalize_whisper_job(job, worker_result)

        save_video_info.assert_not_called()
        save_whisper_cache.assert_not_called()
        save_subtitle.assert_not_called()
        save_cache.assert_not_called()
        log_usage.assert_not_called()

    async def test_subtitle_only_background_commit_is_atomic(self):
        from core import background_pipeline

        info = VideoInfo(title="New title", webpage_url=URL, id="demo", extractor="example")
        job = {
            "task_id": "job-subtitle",
            "url": URL,
            "user_id": 7,
            "guest_id": None,
            "lang": "zh",
            "payload": {"pipeline": "subtitle_only"},
        }
        worker_result = {
            "subtitle_text": "Raw transcript text long enough to pass validation.",
            "language": "zh",
        }

        with (
            patch.object(background_pipeline, "_load_video_info", AsyncMock(return_value=info)),
            patch.object(background_pipeline, "save_video_info_cache", create=True) as save_video_info,
            patch.object(
                background_pipeline,
                "correct_subtitle_text",
                AsyncMock(return_value="Corrected transcript text long enough to pass validation."),
            ),
            patch.object(background_pipeline, "save_whisper_cache", create=True) as save_whisper_cache,
            patch.object(background_pipeline, "save_subtitle", create=True) as save_subtitle,
            patch.object(
                background_pipeline,
                "commit_subtitle_generation",
                create=True,
            ) as commit_subtitle_generation,
            patch.object(background_pipeline.job_store, "update_job"),
        ):
            result = await background_pipeline.finalize_whisper_job(job, worker_result)

        self.assertEqual("whisper", result["source"])
        commit_subtitle_generation.assert_called_once()
        save_video_info.assert_not_called()
        save_whisper_cache.assert_not_called()
        save_subtitle.assert_not_called()


class GenerationTransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "knowledge.db"
        self.original_db_path = database.DB_PATH
        database.DB_PATH = self.db_path
        cache._initialized = False
        database.init_db()
        cache.init_cache()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        cache._initialized = False
        self.tmp.cleanup()

    def _seed_old_records(self):
        cache.save_cache(
            URL,
            video_title="Old title",
            subtitle_text="Old subtitle",
            source="old-source",
            result_json=json.dumps({"result": {"summary": "Old shared summary"}}),
            fingerprint="example:demo",
            part_info="old-part",
            platform="example",
            prompt_version=1,
        )
        cache.save_video_info_cache(
            URL,
            {"title": "Old title", "duration": 30, "description": "Old description"},
            fingerprint="example:demo",
        )
        cache.save_whisper_cache(
            URL,
            "Old whisper subtitle",
            language="zh",
            raw_text="Old raw whisper subtitle",
            fingerprint="example:demo",
        )
        database.save_subtitle_to_db(
            URL,
            "old-source",
            "zh",
            "Old persisted subtitle",
            title="Old title",
            platform="example",
            part_info="old-part",
        )

    def _snapshot(self):
        with database.get_db() as conn:
            return {
                "ai": tuple(
                    conn.execute(
                        "SELECT video_title, subtitle_text, source, result_json, part_info "
                        "FROM ai_cache WHERE url_hash = ?",
                        (cache._url_hash(URL),),
                    ).fetchone()
                ),
                "info": tuple(
                    conn.execute(
                        "SELECT title, info_json FROM video_info_cache WHERE url_hash = ?",
                        (cache._url_hash(URL),),
                    ).fetchone()
                ),
                "video": tuple(
                    conn.execute(
                        "SELECT title, platform, status, part_info FROM videos WHERE url = ?",
                        (URL,),
                    ).fetchone()
                ),
                "subtitle": tuple(
                    conn.execute(
                        "SELECT s.source, s.language, s.full_text FROM subtitles s "
                        "JOIN videos v ON v.id = s.video_id WHERE v.url = ?",
                        (URL,),
                    ).fetchone()
                ),
                "whisper": tuple(
                    conn.execute(
                        "SELECT subtitle_text, language, raw_text FROM whisper_cache "
                        "WHERE url_hash = ?",
                        (cache._url_hash(URL),),
                    ).fetchone()
                ),
                "usage": conn.execute("SELECT COUNT(*) FROM usage_logs").fetchone()[0],
                "history": conn.execute("SELECT COUNT(*) FROM user_history").fetchone()[0],
            }

    @staticmethod
    def _new_info():
        return {
            "title": "New title",
            "webpage_url": URL,
            "id": "demo",
            "extractor": "example",
            "duration": 60,
            "description": "New description",
        }

    @staticmethod
    def _new_result():
        return {
            "result": {"summary": "New validated summary", "chapters": []},
            "mindmap_markdown": "",
            "notes": "New notes",
            "qa_pairs": [],
        }

    def _commit(self, result=None, info=None):
        from core.generation_commit import commit_full_generation

        return commit_full_generation(
            url=URL,
            info=info if info is not None else self._new_info(),
            fingerprint="example:demo",
            subtitle_text="New persisted subtitle",
            subtitle_source="whisper",
            subtitle_language="zh",
            part_info="new-part",
            platform="example",
            result=result if result is not None else self._new_result(),
            prompt_version=2,
            user_id=7,
            guest_id=None,
            whisper_raw_text="New raw whisper subtitle",
        )

    def test_empty_summary_is_rejected_before_any_record_changes(self):
        from core.generation_commit import InvalidGenerationResult

        self._seed_old_records()
        before = self._snapshot()
        invalid = self._new_result()
        invalid["result"]["summary"] = "   "

        with self.assertRaises(InvalidGenerationResult):
            self._commit(invalid)

        self.assertEqual(before, self._snapshot())

    def test_nonserializable_result_is_rejected_before_any_record_changes(self):
        from core.generation_commit import InvalidGenerationResult

        self._seed_old_records()
        before = self._snapshot()
        invalid = self._new_result()
        invalid["notes"] = {"not", "json"}

        with self.assertRaises(InvalidGenerationResult):
            self._commit(invalid)

        self.assertEqual(before, self._snapshot())

    def test_transaction_failure_rolls_back_every_replacement_and_usage(self):
        self._seed_old_records()
        before = self._snapshot()
        with database.get_db() as conn:
            conn.execute(
                """
                CREATE TRIGGER reject_success_usage
                BEFORE INSERT ON usage_logs
                WHEN NEW.status = 'SUCCESS'
                BEGIN
                    SELECT RAISE(FAIL, 'usage insert rejected');
                END
                """
            )

        with self.assertRaisesRegex(sqlite3.IntegrityError, "usage insert rejected"):
            self._commit()

        self.assertEqual(before, self._snapshot())

    def test_success_replaces_all_records_and_logs_usage_once(self):
        self._seed_old_records()

        encoded = self._commit()

        self.assertEqual("New validated summary", json.loads(encoded)["result"]["summary"])
        snapshot = self._snapshot()
        self.assertEqual("New title", snapshot["ai"][0])
        self.assertEqual("New persisted subtitle", snapshot["ai"][1])
        self.assertEqual("whisper", snapshot["ai"][2])
        self.assertEqual("new-part", snapshot["ai"][4])
        self.assertEqual("New title", snapshot["info"][0])
        self.assertEqual(("New title", "example", "done", "new-part"), snapshot["video"])
        self.assertEqual(("whisper", "zh", "New persisted subtitle"), snapshot["subtitle"])
        self.assertEqual(
            ("New persisted subtitle", "zh", "New raw whisper subtitle"),
            snapshot["whisper"],
        )
        self.assertEqual(1, snapshot["usage"])
        self.assertEqual(1, snapshot["history"])

    def test_successful_commit_enforces_cache_retention_and_keeps_new_result(self):
        for index in range(50):
            cached_url = f"https://www.example.com/video/cached-{index}"
            cache.save_cache(
                cached_url,
                video_title=f"Cached {index}",
                result_json=json.dumps({"result": {"summary": f"Summary {index}"}}),
                fingerprint=f"example:cached-{index}",
                prompt_version=1,
            )

        self._commit()

        with database.get_db() as conn:
            cache_count = conn.execute("SELECT COUNT(*) FROM ai_cache").fetchone()[0]
            committed = conn.execute(
                "SELECT result_json FROM ai_cache WHERE url_hash = ?",
                (cache._url_hash(URL),),
            ).fetchone()

        self.assertEqual(50, cache_count)
        self.assertIsNotNone(committed)
        self.assertEqual(
            "New validated summary",
            json.loads(committed["result_json"])["result"]["summary"],
        )

    def test_sparse_success_preserves_existing_optional_video_metadata(self):
        self._seed_old_records()
        with database.get_db() as conn:
            conn.execute(
                """
                UPDATE videos
                SET uploader = ?, duration = ?, thumbnail_url = ?, description = ?
                WHERE url = ?
                """,
                (
                    "Old uploader",
                    30,
                    "https://www.example.com/old-thumbnail.jpg",
                    "Old description",
                    URL,
                ),
            )

        sparse_info = self._new_info()
        sparse_info.update(
            {
                "uploader": None,
                "duration": None,
                "thumbnail": "",
                "description": "",
            }
        )
        self._commit(info=sparse_info)

        with database.get_db() as conn:
            video = conn.execute(
                """
                SELECT title, uploader, duration, thumbnail_url, description
                FROM videos WHERE url = ?
                """,
                (URL,),
            ).fetchone()

        self.assertEqual("New title", video["title"])
        self.assertEqual("Old uploader", video["uploader"])
        self.assertEqual(30, video["duration"])
        self.assertEqual(
            "https://www.example.com/old-thumbnail.jpg",
            video["thumbnail_url"],
        )
        self.assertEqual("Old description", video["description"])


if __name__ == "__main__":
    unittest.main()
