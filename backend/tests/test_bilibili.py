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
    def test_default_credential_policy_is_limited_to_login_metadata(self):
        with patch.dict(os.environ), patch("core.platform_config.get_cookie", return_value="SESSDATA=unit-test"):
            os.environ.pop("BILIBILI_USE_ACCOUNT_COOKIE", None)
            os.environ.pop("BILIBILI_COOKIE_SCOPE", None)
            for path in (
                "/x/web-interface/nav", "/x/space/wbi/arc/search", "/x/player/v2",
                "/x/player/wbi/v2", "/x/v2/dm/view",
            ):
                with self.subTest(path=path):
                    self.assertEqual("SESSDATA=unit-test", bilibili.cookie_for_url(
                        f"https://api.bilibili.com{path}?id=test",
                    ))
            for url in (
                "https://www.bilibili.com/video/BV1test",
                "https://api.bilibili.com/x/player/wbi/playurl",
                "https://aisubtitle.hdslb.com/subtitle.json",
                "https://api.bilibili.com.evil.invalid/x/player/v2",
                "http://api.bilibili.com/x/player/v2",
            ):
                with self.subTest(url=url):
                    self.assertEqual("", bilibili.cookie_for_url(url))

    def test_metadata_policy_does_not_write_account_cookie_to_yt_dlp_file(self):
        with (
            patch.dict(os.environ, {"BILIBILI_USE_ACCOUNT_COOKIE": "true", "BILIBILI_COOKIE_SCOPE": "metadata"}),
            patch("core.platform_config.get_cookie", return_value="SESSDATA=unit-test; bili_jct=token"),
            patch.object(bilibili, "_cookiefile_path", None),
        ):
            path = bilibili._cookiefile()
            try:
                content = Path(path).read_text()
            finally:
                bilibili._cleanup_cookiefile(path)
        self.assertNotIn("SESSDATA", content)
        self.assertNotIn("unit-test", content)
        self.assertNotIn("bili_jct", content)

    def test_explicit_all_policy_still_scopes_credentials_to_https_bilibili(self):
        with (
            patch.dict(os.environ, {"BILIBILI_USE_ACCOUNT_COOKIE": "true", "BILIBILI_COOKIE_SCOPE": "all"}),
            patch("core.platform_config.get_cookie", return_value="SESSDATA=unit-test"),
        ):
            self.assertEqual("SESSDATA=unit-test", bilibili.cookie_for_url("https://www.bilibili.com/video/BV1test"))
            self.assertEqual("", bilibili.cookie_for_url("https://video.bilivideo.com/video.m4s"))
            self.assertEqual("", bilibili.cookie_for_url("http://www.bilibili.com/video/BV1test"))

    def test_explicit_opt_out_disables_metadata_and_all_credentials(self):
        with patch("core.platform_config.get_cookie", return_value="SESSDATA=unit-test") as credential:
            for scope in ("metadata", "all"):
                with patch.dict(os.environ, {"BILIBILI_USE_ACCOUNT_COOKIE": "false", "BILIBILI_COOKIE_SCOPE": scope}):
                    self.assertEqual("", bilibili.cookie_for_url("https://api.bilibili.com/x/player/v2"))
                    self.assertEqual("", bilibili.cookie_for_url("https://www.bilibili.com/video/BV1test"))
            credential.assert_not_called()

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
        with patch.dict(os.environ, {"BILIBILI_COOKIE": "SESSDATA=abc; bili_jct=xyz", "BILIBILI_USE_ACCOUNT_COOKIE": "true", "BILIBILI_COOKIE_SCOPE": "all"}):
            with patch.object(bilibili, "_cookiefile_path", None), patch("core.platform_config.get_cookie", return_value="SESSDATA=abc; bili_jct=xyz"):
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
            "已停止访问",
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
