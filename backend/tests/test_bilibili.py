import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from core import bilibili


class YdlOptsTests(unittest.TestCase):
    def test_non_bilibili_urls_get_no_extra_opts(self):
        self.assertEqual({}, bilibili.ydl_opts_for("https://www.youtube.com/watch?v=x"))
        self.assertEqual({}, bilibili.ydl_opts_for(""))
        self.assertEqual(
            {},
            bilibili.ydl_opts_for("https://www.douyin.com/video/1", "https://v.douyin.com/x"),
        )

    def test_bilibili_urls_get_cookiefile_and_browser_headers(self):
        opts = bilibili.ydl_opts_for(
            "https://www.bilibili.com/video/BV1EmJ96qEtZ",
            "https://audio.example.com/best.m4s",
        )
        self.assertIn("cookiefile", opts)
        self.assertEqual("https://www.bilibili.com/", opts["http_headers"]["Referer"])
        self.assertIn("Mozilla", opts["http_headers"]["User-Agent"])
        cookiefile = opts["cookiefile"]
        self.assertTrue(os.path.isfile(cookiefile))
        self.assertEqual(0o600, os.stat(cookiefile).st_mode & 0o777)

    def test_cookiefile_scopes_cookies_to_bilibili_domain(self):
        with patch.dict(os.environ, {"BILIBILI_COOKIE": "SESSDATA=abc; bili_jct=xyz"}):
            with patch.object(bilibili, "_cookiefile_path", None):
                path = bilibili._cookiefile()
                try:
                    lines = Path(path).read_text().strip().splitlines()
                finally:
                    bilibili._cleanup_cookiefile(path)
        cookie_rows = [ln for ln in lines if not ln.startswith("#")]
        self.assertEqual(2, len(cookie_rows))
        for row in cookie_rows:
            fields = row.split("\t")
            self.assertEqual(".bilibili.com", fields[0])
            self.assertEqual("TRUE", fields[1])
            self.assertEqual("/", fields[2])
        names = {row.split("\t")[5] for row in cookie_rows}
        self.assertEqual({"SESSDATA", "bili_jct"}, names)


class ErrorMessageTests(unittest.TestCase):
    def test_translates_risk_control_and_gone_errors(self):
        self.assertIn(
            "BILIBILI_COOKIE",
            bilibili.ytdlp_error_message(RuntimeError("HTTP Error 412: Precondition Failed")),
        )
        self.assertIn(
            "付费",
            bilibili.ytdlp_error_message(RuntimeError(
                "ERROR: [BiliBili] x: This video may be deleted or geo-restricted."
            )),
        )
        self.assertEqual(
            "下载超时",
            bilibili.ytdlp_error_message(RuntimeError("下载超时")),
        )


if __name__ == "__main__":
    unittest.main()
