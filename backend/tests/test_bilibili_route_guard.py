"""Bilibili protection at public HTTP routes; all upstream traffic is mocked."""

import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException

from api import routes
from core import bilibili_guard
from core.models import ParseRequest


class BilibiliRouteGuardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        for name, value in (
            ("STATE_PATH", Path(temporary.name) / "guard.db"),
            ("LIMITS", {"api": (0, ((3600, 60),)), "media": (0, ((3600, 1200),))}),
        ):
            patched = patch.object(bilibili_guard, name, value)
            patched.start()
            self.addCleanup(patched.stop)

    def test_short_link_risk_stops_before_downloader_and_closes_connection(self):
        response = Mock(status=412)
        connection = Mock()
        connection.getresponse.return_value = response
        with (
            patch.object(routes, "require_identity", return_value={"user_id": 1}),
            patch.object(routes.http.client, "HTTPSConnection", return_value=connection),
            patch.object(routes.downloader, "parse_info") as parse,
        ):
            for _ in range(2):
                with self.assertRaises(HTTPException) as raised:
                    routes._parse_video(ParseRequest(url="https://b23.tv/test"), Mock())
                self.assertEqual(429, raised.exception.status_code)
            parse.assert_not_called()
        connection.request.assert_called_once()
        response.close.assert_called_once()
        self.assertEqual(2, connection.close.call_count)

    def test_short_link_preserves_part_and_closes_success_response(self):
        response = Mock(status=302)
        response.getheader.return_value = "https://www.bilibili.com/video/BV1test?p=3"
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.object(routes.http.client, "HTTPSConnection", return_value=connection):
            resolved = routes._resolve_short_url("https://b23.tv/test")
        self.assertEqual("https://www.bilibili.com/video/BV1test?p=3", resolved)
        response.close.assert_called_once()
        connection.close.assert_called_once()

    def test_refresh_uses_guarded_downloader(self):
        url = "https://www.bilibili.com/video/BV1test"
        downloader = Mock()
        downloader.extract_info.return_value = {"formats": []}
        with (
            patch.object(routes, "require_identity", return_value={"user_id": 1}),
            patch.object(routes, "ensure_public_http_url"),
            patch.object(routes, "ydl_opts_for", return_value={}),
            patch.object(routes, "youtube_dl", return_value=nullcontext(downloader)) as guarded,
        ):
            result = routes._refresh_stream_url(url, Mock())
        self.assertIsNone(result["stream_url"])
        self.assertEqual(url, guarded.call_args.args[1])
        downloader.extract_info.assert_called_once_with(url, download=False)

    def test_refresh_preserves_protection_message(self):
        with (
            patch.object(routes, "require_identity", return_value={"user_id": 1}),
            patch.object(routes, "ensure_public_http_url"),
            patch.object(routes, "ydl_opts_for", return_value={}),
            patch.object(routes, "youtube_dl", side_effect=bilibili_guard.BilibiliAccessBlocked("访问已暂停")),
        ):
            with self.assertRaises(HTTPException) as raised:
                routes._refresh_stream_url("https://www.bilibili.com/video/BV1test", Mock())
        self.assertEqual(429, raised.exception.status_code)
        self.assertEqual("访问已暂停", raised.exception.detail)
