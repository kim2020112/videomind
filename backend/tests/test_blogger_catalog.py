import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from core.blogger.catalog import (
    BilibiliCatalogClient,
    CatalogError,
    parse_creator_input,
    parse_length,
    sign_wbi,
)


class ParseCreatorInputTests(unittest.TestCase):
    def test_accepts_numeric_uid(self):
        self.assertEqual("475210", parse_creator_input("475210"))

    def test_accepts_space_url(self):
        self.assertEqual(
            "475210",
            parse_creator_input("https://space.bilibili.com/475210?spm_id_from=333"),
        )

    def test_accepts_mobile_space_url_in_shared_text(self):
        self.assertEqual(
            "475210",
            parse_creator_input("看这个UP https://m.bilibili.com/space/475210 很棒"),
        )

    def test_rejects_nickname_search(self):
        with self.assertRaises(CatalogError) as raised:
            parse_creator_input("老师好我叫何同学")
        self.assertEqual("invalid_input", raised.exception.code)

    def test_rejects_single_video_url(self):
        with self.assertRaises(CatalogError) as raised:
            parse_creator_input("https://www.bilibili.com/video/BV1xx411c7mD")
        self.assertEqual("invalid_input", raised.exception.code)

    def test_rejects_credentials_or_ports(self):
        with self.assertRaises(CatalogError):
            parse_creator_input("https://user:pass@space.bilibili.com/475210")


class SignWbiTests(unittest.TestCase):
    def test_signature_is_deterministic_and_sorted(self):
        mixin = "a" * 32
        signed = sign_wbi({"mid": 1, "wts": 1700000000, "order": "pubdate"}, mixin)
        self.assertIn("w_rid", signed)
        again = sign_wbi({"order": "pubdate", "wts": 1700000000, "mid": 1}, mixin)
        self.assertEqual(signed["w_rid"], again["w_rid"])

    def test_signature_strips_special_chars(self):
        mixin = "a" * 32
        signed = sign_wbi({"q": "he's (test)*!"}, mixin)
        self.assertEqual("hes test", signed["q"])


class ParseLengthTests(unittest.TestCase):
    def test_parses_mm_ss(self):
        self.assertEqual(754, parse_length("12:34"))

    def test_parses_hh_mm_ss(self):
        self.assertEqual(3723, parse_length("1:02:03"))

    def test_parses_seconds(self):
        self.assertEqual(30, parse_length("30"))


class ErrorMappingTests(unittest.TestCase):
    def _client_with_payload(self, payload, status_code=200):
        client = BilibiliCatalogClient(cookie="buvid3=test")
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = payload
        return client, response

    def _get_error(self, payload, status_code=200):
        client, response = self._client_with_payload(payload, status_code)
        with patch("core.blogger.catalog.httpx.get", return_value=response):
            with patch("core.blogger.catalog.time.sleep"):
                with self.assertRaises(CatalogError) as raised:
                    client.get("/x/web-interface/nav")
        return raised.exception

    def test_login_codes(self):
        self.assertEqual("login", self._get_error({"code": -101}).code)
        self.assertEqual("login", self._get_error({"code": -111}).code)

    def test_risk_codes(self):
        for code in (-352, -412, -509, -799):
            self.assertEqual("rate_limit", self._get_error({"code": code}).code)

    def test_http_block_without_cookie_is_login_guidance(self):
        # 无 SESSDATA 时 412 是「空间接口需要登录」，不是可重试的限流
        self.assertEqual("login", self._get_error({}, status_code=412).code)

    def test_http_rate_limit_with_cookie(self):
        client = BilibiliCatalogClient(cookie="SESSDATA=abc; buvid3=x")
        response = MagicMock()
        response.status_code = 412
        response.json.return_value = {}
        with patch("core.blogger.catalog.httpx.get", return_value=response):
            with patch("core.blogger.catalog.time.sleep"):
                with self.assertRaises(CatalogError) as raised:
                    client.get("/x/space/wbi/arc/search")
        self.assertEqual("rate_limit", raised.exception.code)

    def test_not_found_is_unavailable(self):
        self.assertEqual("unavailable", self._get_error({"code": -404}).code)

    def test_malformed_payload_is_api_error_not_empty(self):
        self.assertEqual("api", self._get_error({"code": 0, "data": []}).code)

    def test_success_returns_data(self):
        client, response = self._client_with_payload({"code": 0, "data": {"ok": 1}})
        with patch("core.blogger.catalog.httpx.get", return_value=response):
            with patch("core.blogger.catalog.time.sleep"):
                self.assertEqual({"ok": 1}, client.get("/x/web-interface/nav"))


if __name__ == "__main__":
    unittest.main()
