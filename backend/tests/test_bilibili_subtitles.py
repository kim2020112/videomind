import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from core import summarizer
from core.models import VideoInfo, VideoPart
from core.pipeline import subtitle as subtitle_pipeline
from core.summary_models import SummarizeRequest


SUBTITLE_META = {
    "code": 0,
    "data": {
        "subtitle": {
            "subtitles": [
                {
                    "lan": "zh-Hans",
                    "subtitle_url": "//example.com/subtitle.json",
                }
            ]
        }
    },
}
SUBTITLE_BODY = {
    "body": [
        {"from": 1.25, "to": 3.5, "content": "第一句字幕"},
        {"from": 4.0, "to": 7.0, "content": "第二句字幕"},
    ]
}
LOGIN_HIDDEN_META = {
    "code": 0,
    "data": {
        "aid": 99,
        "need_login_subtitle": True,
        "subtitle": {"subtitles": []},
    },
}


class BilibiliSubtitleExtractorTests(unittest.TestCase):
    def test_public_api_requests_include_an_anonymous_device_cookie(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({"code": 0, "data": {}}).encode()

        with patch.object(summarizer.urllib.request, "urlopen", return_value=Response()) as urlopen:
            summarizer._fetch_bilibili_json("https://api.bilibili.com/x/player/v2", retries=1)

        request = urlopen.call_args.args[0]
        cookie = request.get_header("Cookie")
        self.assertIn("buvid3=", cookie)
        self.assertIn("b_nut=", cookie)

    def test_returns_available_subtitle_from_player_metadata(self):
        with patch.object(
            summarizer,
            "_fetch_bilibili_json",
            side_effect=[SUBTITLE_META, SUBTITLE_BODY],
        ):
            result = summarizer.extract_bilibili_subtitle_by_cid("BV1demo", 2024)

        self.assertTrue(result["has_subtitle"])
        self.assertEqual("zh-Hans", result["language"])
        self.assertIn("[00:01] 第一句字幕", result["text"])


class BilibiliDownloaderTests(unittest.TestCase):
    def test_short_link_resolution_is_case_insensitive_and_preserves_part(self):
        from api import routes

        class Response:
            def getheader(self, name):
                if name == "Location":
                    return "https://www.bilibili.com/video/BV1demo?p=20&share_source=copy_web"
                return None

        connection = MagicMock()
        connection.getresponse.return_value = Response()
        with patch.object(routes.http.client, "HTTPSConnection", return_value=connection):
            resolved = routes._resolve_short_url("https://B23.TV/AbCd")

        self.assertEqual(
            "https://www.bilibili.com/video/BV1demo?p=20",
            resolved,
        )

    def test_explicit_part_uses_selected_part_duration(self):
        from core import downloader as downloader_module

        class FakeYoutubeDL:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def extract_info(self, _url, download=False):
                return {
                    "id": "BV1demo_p20",
                    "title": "Demo course p20 Part twenty",
                    "webpage_url": "https://www.bilibili.com/video/BV1demo",
                    "duration": 538,
                    "extractor": "BiliBili",
                    "formats": [],
                }

        parts = [
            VideoPart(index=1, title="Part one", duration=1000),
            VideoPart(index=20, title="Part twenty", duration=538),
            VideoPart(index=21, title="Part twenty-one", duration=600),
        ]
        with (
            tempfile.TemporaryDirectory() as output_dir,
            patch.object(downloader_module.yt_dlp, "YoutubeDL", return_value=FakeYoutubeDL()),
            patch.object(downloader_module, "_fetch_bilibili_parts", return_value=parts),
        ):
            info = downloader_module.VideoDownloader(output_dir=output_dir).parse_info(
                "https://www.bilibili.com/video/BV1demo?p=20"
            )

        self.assertEqual(538, info.duration)

    def test_base_multipart_url_uses_total_duration_even_when_id_contains_p1(self):
        from core import downloader as downloader_module

        class FakeYoutubeDL:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def extract_info(self, _url, download=False):
                return {
                    "id": "BV1demo_p1",
                    "title": "Demo course",
                    "webpage_url": "https://www.bilibili.com/video/BV1demo",
                    "duration": 1000,
                    "extractor": "BiliBili",
                    "formats": [],
                }

        parts = [
            VideoPart(index=1, title="Part one", duration=1000),
            VideoPart(index=20, title="Part twenty", duration=538),
            VideoPart(index=21, title="Part twenty-one", duration=600),
        ]
        with (
            tempfile.TemporaryDirectory() as output_dir,
            patch.object(downloader_module.yt_dlp, "YoutubeDL", return_value=FakeYoutubeDL()),
            patch.object(downloader_module, "_fetch_bilibili_parts", return_value=parts),
        ):
            info = downloader_module.VideoDownloader(output_dir=output_dir).parse_info(
                "https://www.bilibili.com/video/BV1demo"
            )

        self.assertEqual(2138, info.duration)


class BilibiliSubtitleFallbackTests(unittest.TestCase):
    def test_successful_empty_track_list_is_explicitly_absent(self):
        empty_meta = {"code": 0, "data": {"subtitle": {"subtitles": []}}}
        with patch.object(summarizer, "_fetch_bilibili_json", return_value=empty_meta):
            result = summarizer.extract_bilibili_subtitle_by_cid("BV1demo", 2024)

        self.assertEqual({"has_subtitle": False, "reason": "absent"}, result)

    def test_login_hidden_empty_list_uses_the_fallback_endpoint(self):
        with patch.object(
            summarizer,
            "_fetch_bilibili_json",
            side_effect=[LOGIN_HIDDEN_META, SUBTITLE_META, SUBTITLE_BODY],
        ) as fetch_json:
            result = summarizer.extract_bilibili_subtitle_by_cid("BV1demo", 2024)

        self.assertTrue(result["has_subtitle"])
        self.assertEqual(3, fetch_json.call_count)

    def test_login_hidden_tracks_are_unavailable_when_fallback_is_rate_limited(self):
        with patch.object(
            summarizer,
            "_fetch_bilibili_json",
            side_effect=[LOGIN_HIDDEN_META, RuntimeError("rate limited")],
        ):
            result = summarizer.extract_bilibili_subtitle_by_cid("BV1demo", 2024)

        self.assertIsNone(result)

    def test_uses_fallback_endpoint_after_primary_lookup_failure(self):
        with patch.object(
            summarizer,
            "_fetch_bilibili_json",
            side_effect=[RuntimeError("rate limited"), SUBTITLE_META, SUBTITLE_BODY],
        ) as fetch_json:
            result = summarizer.extract_bilibili_subtitle_by_cid("BV1demo", 2024, aid=99)

        self.assertTrue(result["has_subtitle"])
        self.assertEqual(3, fetch_json.call_count)

    def test_discovers_aid_before_fallback_when_primary_lookup_fails(self):
        view_meta = {"code": 0, "data": {"aid": 99}}
        with patch.object(
            summarizer,
            "_fetch_bilibili_json",
            side_effect=[RuntimeError("rate limited"), view_meta, SUBTITLE_META, SUBTITLE_BODY],
        ) as fetch_json:
            result = summarizer.extract_bilibili_subtitle_by_cid("BV1demo", 2024)

        self.assertTrue(result["has_subtitle"])
        self.assertEqual(4, fetch_json.call_count)

    def test_part_url_without_cached_cid_never_falls_back_to_p1(self):
        with (
            patch.object(subtitle_pipeline, "extract_bilibili_subtitle") as p1_lookup,
            patch.object(subtitle_pipeline, "extract_bilibili_subtitle_by_cid") as part_lookup,
        ):
            result = subtitle_pipeline.try_get_bilibili_cc_subtitle(
                "https://www.bilibili.com/video/BV1demo?p=20"
            )

        self.assertIsNone(result)
        p1_lookup.assert_not_called()
        part_lookup.assert_not_called()


class BilibiliSubtitlePipelineTests(unittest.IsolatedAsyncioTestCase):
    def test_quick_check_accepts_a_short_but_valid_bilibili_track(self):
        from api import stream_routes

        info = VideoInfo(
            title="Short demo",
            webpage_url="https://www.bilibili.com/video/BV1demo",
            extractor="BiliBili",
        )
        with (
            patch.object(subtitle_pipeline, "get_subtitle_from_db", return_value=None),
            patch.object(
                subtitle_pipeline,
                "try_get_bilibili_cc_subtitle",
                return_value={"has_subtitle": True, "text": "[00:01] 简短字幕"},
            ),
        ):
            result = stream_routes._quick_subtitle_check(info.webpage_url, info)

        self.assertTrue(result)

    async def test_single_selected_part_metadata_uses_its_exact_cid(self):
        url = "https://www.bilibili.com/video/BV1demo?p=20"
        info = VideoInfo(
            title="Demo",
            webpage_url=url,
            extractor="BiliBili",
            parts=[VideoPart(index=20, title="Part 20", cid=2024)],
        )
        available = {
            "has_subtitle": True,
            "language": "zh-Hans",
            "text": "[00:01] 这是当前分P的字幕内容，长度足够用于生成学习总结。",
        }

        with (
            patch.object(subtitle_pipeline, "get_subtitle_from_db", return_value=None),
            patch.object(
                subtitle_pipeline,
                "extract_bilibili_subtitle_by_cid",
                return_value=available,
            ) as part_lookup,
            patch.object(subtitle_pipeline, "extract_bilibili_subtitle", return_value=None) as p1_lookup,
        ):
            text, source, language = await subtitle_pipeline.fetch_subtitle(url, info)

        self.assertEqual(available["text"], text)
        self.assertEqual("bilibili_cc", source)
        self.assertEqual("zh-Hans", language)
        part_lookup.assert_called_once_with("BV1demo", 2024)
        p1_lookup.assert_not_called()

    async def test_short_link_uses_canonical_bilibili_url_for_cc_lookup(self):
        short_url = "https://B23.TV/demo"
        canonical_url = "https://www.bilibili.com/video/BV1demo?p=20"
        info = VideoInfo(
            title="Demo",
            webpage_url=canonical_url,
            id="BV1demo_p20",
            extractor="BiliBili",
            parts=[VideoPart(index=20, title="Part 20", cid=2024, duration=538)],
        )
        available = {
            "has_subtitle": True,
            "language": "zh-Hans",
            "text": "[00:01] 这是短链接对应分P的字幕内容，长度足够用于生成学习总结。",
        }

        with (
            patch.object(subtitle_pipeline, "get_subtitle_from_db", return_value=None),
            patch.object(
                subtitle_pipeline,
                "extract_bilibili_subtitle_by_cid",
                return_value=available,
            ) as part_lookup,
        ):
            text, source, language = await subtitle_pipeline.fetch_subtitle(short_url, info)

        self.assertEqual(available["text"], text)
        self.assertEqual("bilibili_cc", source)
        self.assertEqual("zh-Hans", language)
        part_lookup.assert_called_once_with("BV1demo", 2024)

    async def test_unavailable_bilibili_lookup_is_not_treated_as_absent(self):
        info = VideoInfo(
            title="Demo",
            webpage_url="https://www.bilibili.com/video/BV1demo",
            extractor="BiliBili",
        )
        with (
            patch.object(subtitle_pipeline, "get_subtitle_from_db", return_value=None),
            patch.object(subtitle_pipeline, "extract_bilibili_subtitle", return_value=None),
        ):
            with self.assertRaises(RuntimeError) as raised:
                await subtitle_pipeline.fetch_subtitle(info.webpage_url, info)

        self.assertIn("字幕接口暂时不可用", str(raised.exception))

    async def test_stream_does_not_enqueue_whisper_when_cc_lookup_is_unavailable(self):
        from api import stream_routes

        url = "https://www.bilibili.com/video/BV1demo?p=20"
        cached_info = {
            "title": "Demo",
            "webpage_url": url,
            "id": "BV1demo_p20",
            "extractor": "BiliBili",
            "duration": 600,
            "parts": [{"index": 20, "title": "Part 20", "cid": 2024, "duration": 600}],
        }
        info = VideoInfo(
            title="Demo",
            webpage_url=url,
            id="BV1demo_p20",
            extractor="BiliBili",
            duration=600,
            parts=[VideoPart(index=20, title="Part 20", cid=2024, duration=600)],
        )

        with (
            patch.object(stream_routes, "is_ai_available", return_value=True),
            patch.object(stream_routes, "extract_url", return_value=url),
            patch.object(stream_routes, "ensure_public_http_url"),
            patch.object(stream_routes, "require_identity", return_value={"user_id": 1, "guest_id": None}),
            patch.object(stream_routes, "get_cached", return_value=None),
            patch.object(stream_routes, "check_usage_limit", return_value=(True, 0, 20)),
            patch.object(stream_routes, "get_video_info_cache", return_value=cached_info),
            patch.object(stream_routes, "find_active_job", return_value=None),
            patch.object(stream_routes, "_quick_db_subtitle_check", return_value=False),
            patch.object(stream_routes, "get_whisper_cache", return_value=None),
            patch.object(stream_routes, "is_whisper_available", return_value=True),
            patch.object(subtitle_pipeline, "try_get_bilibili_cc_subtitle", return_value=None),
            patch.object(stream_routes.downloader, "parse_info", return_value=info),
            patch.object(stream_routes, "save_video_info_cache", create=True),
            patch.object(stream_routes, "_quick_subtitle_check", return_value=None),
            patch.object(stream_routes, "fetch_subtitle", side_effect=RuntimeError("B站字幕接口暂时不可用")),
            patch.object(stream_routes, "enqueue_whisper_job") as enqueue,
        ):
            with self.assertRaises(HTTPException):
                await stream_routes.summarize_stream(
                    SummarizeRequest(url=url),
                    object(),
                )

        enqueue.assert_not_called()

    async def test_stream_can_enqueue_whisper_after_explicit_absence(self):
        from api import stream_routes

        url = "https://www.bilibili.com/video/BV1demo"
        cached_info = {
            "title": "Demo",
            "webpage_url": url,
            "id": "BV1demo",
            "extractor": "BiliBili",
            "duration": 600,
            "parts": [],
        }
        job = {
            "task_id": "task-1",
            "url_hash": "hash-1",
            "estimated_seconds": 60,
            "queue_position": 1,
        }

        with (
            patch.object(stream_routes, "is_ai_available", return_value=True),
            patch.object(stream_routes, "extract_url", return_value=url),
            patch.object(stream_routes, "ensure_public_http_url"),
            patch.object(stream_routes, "require_identity", return_value={"user_id": 1, "guest_id": None}),
            patch.object(stream_routes, "get_cached", return_value=None),
            patch.object(stream_routes, "check_usage_limit", return_value=(True, 0, 20)),
            patch.object(stream_routes, "get_video_info_cache", return_value=cached_info),
            patch.object(stream_routes, "find_active_job", return_value=None),
            patch.object(stream_routes, "_quick_db_subtitle_check", return_value=False),
            patch.object(stream_routes, "get_whisper_cache", return_value=None),
            patch.object(stream_routes, "is_whisper_available", return_value=True),
            patch.object(
                subtitle_pipeline,
                "try_get_bilibili_cc_subtitle",
                return_value={"has_subtitle": False, "reason": "absent"},
            ),
            patch.object(stream_routes, "enqueue_whisper_job", return_value=job) as enqueue,
        ):
            response = await stream_routes.summarize_stream(
                SummarizeRequest(url=url),
                object(),
            )

        self.assertEqual(200, response.status_code)
        enqueue.assert_called_once()

    async def test_stream_uses_selected_part_duration_from_legacy_cached_info(self):
        from api import stream_routes
        from core.whisper import estimate_transcribe_time

        url = "https://www.bilibili.com/video/BV1demo?p=20"
        cached_info = {
            "title": "Demo",
            "webpage_url": url,
            "id": "BV1demo_p20",
            "extractor": "BiliBili",
            "duration": 185910,
            "parts": [
                {"index": 1, "title": "Part 1", "duration": 1000},
                {"index": 20, "title": "Part 20", "duration": 538},
            ],
        }
        job = {
            "task_id": "task-20",
            "url_hash": "hash-20",
            "estimated_seconds": estimate_transcribe_time(538),
            "queue_position": 1,
        }

        with (
            patch.object(stream_routes, "is_ai_available", return_value=True),
            patch.object(stream_routes, "extract_url", return_value=url),
            patch.object(stream_routes, "ensure_public_http_url"),
            patch.object(stream_routes, "require_identity", return_value={"user_id": 1, "guest_id": None}),
            patch.object(stream_routes, "get_cached", return_value=None),
            patch.object(stream_routes, "check_usage_limit", return_value=(True, 0, 20)),
            patch.object(stream_routes, "get_video_info_cache", return_value=cached_info),
            patch.object(stream_routes, "find_active_job", return_value=None),
            patch.object(stream_routes, "_quick_db_subtitle_check", return_value=False),
            patch.object(stream_routes, "get_whisper_cache", return_value=None),
            patch.object(stream_routes, "is_whisper_available", return_value=True),
            patch.object(
                subtitle_pipeline,
                "try_get_bilibili_cc_subtitle",
                return_value={"has_subtitle": False, "reason": "absent"},
            ),
            patch.object(stream_routes, "enqueue_whisper_job", return_value=job) as enqueue,
        ):
            response = await stream_routes.summarize_stream(
                SummarizeRequest(url=url),
                object(),
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            estimate_transcribe_time(538),
            enqueue.call_args.kwargs["estimated_seconds"],
        )

    async def test_subtitle_text_route_does_not_enqueue_on_unavailable_cc_lookup(self):
        from api import subtitle_text_routes

        url = "https://www.bilibili.com/video/BV1demo?p=20"
        info = VideoInfo(
            title="Demo",
            webpage_url=url,
            id="BV1demo_p20",
            extractor="BiliBili",
            duration=600,
            parts=[VideoPart(index=20, title="Part 20", cid=2024, duration=600)],
        )
        job = {
            "task_id": "task-1",
            "url_hash": "hash-1",
            "estimated_seconds": 60,
            "queue_position": 1,
        }

        with (
            patch.object(subtitle_text_routes, "require_identity", return_value={"user_id": 1, "guest_id": None}),
            patch.object(subtitle_text_routes, "extract_url", return_value=url),
            patch.object(subtitle_text_routes, "ensure_public_http_url"),
            patch.object(subtitle_text_routes, "get_subtitle_from_db", return_value=None),
            patch.object(subtitle_text_routes, "extract_bilibili_subtitle_by_cid", return_value=None),
            patch.object(subtitle_text_routes.downloader, "parse_info", return_value=info),
            patch.object(subtitle_text_routes, "get_video_info_cache", return_value=None),
            patch.object(subtitle_text_routes, "save_video_info_cache"),
            patch.object(subtitle_text_routes, "is_whisper_available", return_value=True),
            patch.object(subtitle_text_routes, "check_usage_limit", return_value=(True, 0, 20)),
            patch.object(subtitle_text_routes, "enqueue_whisper_job", return_value=job) as enqueue,
        ):
            with self.assertRaises(HTTPException) as raised:
                await subtitle_text_routes.get_subtitle_text(object(), url=url)

        self.assertEqual(503, raised.exception.status_code)
        enqueue.assert_not_called()

    async def test_subtitle_text_route_uses_canonical_url_after_short_link_parse(self):
        from api import subtitle_text_routes

        short_url = "https://B23.TV/demo"
        canonical_url = "https://www.bilibili.com/video/BV1demo?p=20"
        info = VideoInfo(
            title="Demo",
            webpage_url=canonical_url,
            id="BV1demo_p20",
            extractor="BiliBili",
            duration=538,
            parts=[VideoPart(index=20, title="Part 20", cid=2024, duration=538)],
        )
        available = {
            "has_subtitle": True,
            "language": "zh-Hans",
            "subtitle_type": "auto",
            "text": "[00:01] 这是短链接对应分P的字幕内容，长度足够用于前端展示。",
            "segments": [],
        }

        with (
            patch.object(subtitle_text_routes, "require_identity", return_value={"user_id": 1, "guest_id": None}),
            patch.object(subtitle_text_routes, "extract_url", return_value=short_url),
            patch.object(subtitle_text_routes, "ensure_public_http_url"),
            patch.object(subtitle_text_routes, "get_subtitle_from_db", return_value=None),
            patch.object(subtitle_text_routes, "get_video_info_cache", return_value=None),
            patch.object(subtitle_text_routes.downloader, "parse_info", return_value=info),
            patch.object(subtitle_text_routes, "save_video_info_cache"),
            patch.object(
                subtitle_text_routes,
                "try_get_bilibili_cc_subtitle",
                return_value=available,
            ) as cc_lookup,
            patch.object(subtitle_text_routes, "save_subtitle_to_db"),
            patch.object(subtitle_text_routes, "enqueue_whisper_job") as enqueue,
        ):
            response = await subtitle_text_routes.get_subtitle_text(object(), url=short_url)

        self.assertEqual(available["text"], response["text"])
        cc_lookup.assert_called_once_with(canonical_url, info)
        enqueue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
