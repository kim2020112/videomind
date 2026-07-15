import importlib
import os
import socket
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from starlette.requests import Request


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from api import routes


PUBLIC_IP = "93.184.216.34"


def public_resolver(host, port, *args, **kwargs):
    return [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (PUBLIC_IP, port)),
    ]


class FakeUpstreamResponse:
    def __init__(self, *, status=200, headers=None, body=b""):
        self.status = status
        self.headers = headers or {}
        self._body = body
        self._offset = 0
        self.closed = False

    def getheader(self, name, default=None):
        for key, value in self.headers.items():
            if key.lower() == name.lower():
                return value
        return default

    def read(self, amount=-1):
        if amount is None or amount < 0:
            amount = len(self._body) - self._offset
        chunk = self._body[self._offset:self._offset + amount]
        self._offset += len(chunk)
        return chunk

    def close(self):
        self.closed = True


class SequenceOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, target, headers):
        self.calls.append((target.url, dict(headers)))
        if not self.responses:
            raise AssertionError("unexpected upstream request")
        return self.responses.pop(0)


def load_media_security(testcase):
    try:
        return importlib.import_module("api.media_security")
    except ModuleNotFoundError:
        testcase.fail("api.media_security unified safety layer is missing")


def make_request(*, query="", headers=None):
    raw_headers = [
        (key.lower().encode(), value.encode())
        for key, value in (headers or {}).items()
    ]
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/video/stream",
        "headers": raw_headers,
        "query_string": query.encode(),
    })


class MediaUrlValidationTests(unittest.TestCase):
    def test_allows_https_exact_domain_and_subdomain_labels(self):
        media_security = load_media_security(self)

        for url in (
            "https://hdslb.com/image.jpg",
            "https://i0.hdslb.com/image.jpg",
            "https://rr1---sn.googlevideo.com/video.mp4",
        ):
            with self.subTest(url=url):
                media_security.validate_media_url(url, resolver=public_resolver)

    def test_rejects_http_credentials_unknown_hosts_and_malicious_suffixes(self):
        media_security = load_media_security(self)

        for url in (
            "http://i0.hdslb.com/image.jpg",
            "https://user:password@i0.hdslb.com/image.jpg",
            "https://example.com/image.jpg",
            "https://evilhdslb.com/image.jpg",
            "https://hdslb.com.evil.example/image.jpg",
        ):
            with self.subTest(url=url):
                with self.assertRaises(HTTPException) as raised:
                    media_security.validate_media_url(url, resolver=public_resolver)
                self.assertEqual(400, raised.exception.status_code)

    def test_rejects_target_when_any_dns_result_is_not_public(self):
        media_security = load_media_security(self)

        def mixed_resolver(host, port, *args, **kwargs):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, port)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
            ]

        with self.assertRaises(HTTPException) as raised:
            media_security.validate_media_url(
                "https://i0.hdslb.com/image.jpg",
                resolver=mixed_resolver,
            )

        self.assertEqual(400, raised.exception.status_code)

    def test_rejects_ipv4_and_ipv6_multicast_addresses(self):
        media_security = load_media_security(self)

        for family, address, sockaddr in (
            (socket.AF_INET, "224.0.0.1", ("224.0.0.1", 443)),
            (socket.AF_INET6, "ff02::1", ("ff02::1", 443, 0, 0)),
        ):
            with self.subTest(address=address):
                def resolver(host, port, *args, **kwargs):
                    return [
                        (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr),
                    ]

                with self.assertRaises(HTTPException) as raised:
                    media_security.validate_media_url(
                        "https://i0.hdslb.com/image.jpg",
                        resolver=resolver,
                    )
                self.assertEqual(400, raised.exception.status_code)

    def test_referer_matching_does_not_accept_malicious_suffixes(self):
        self.assertEqual(
            "https://www.bilibili.com/",
            routes._get_cdn_referer("https://i0.hdslb.com/image.jpg"),
        )
        self.assertIsNone(
            routes._get_cdn_referer("https://hdslb.com.evil.example/image.jpg")
        )
        self.assertIsNone(
            routes._get_cdn_referer("https://evilhdslb.com/image.jpg")
        )


class MediaFetchTests(unittest.TestCase):
    def test_default_transport_pins_validated_ip_and_preserves_tls_hostname(self):
        media_security = load_media_security(self)
        resolver_calls = []
        connect_calls = []
        wrap_calls = []
        connection_calls = []

        def resolver(host, port, *args, **kwargs):
            resolver_calls.append((host, port))
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    (PUBLIC_IP, port),
                ),
            ]

        class FakeRawSocket:
            def settimeout(self, timeout):
                self.timeout = timeout

            def connect(self, sockaddr):
                connect_calls.append(sockaddr)

            def close(self):
                pass

        class FakeTlsSocket:
            def close(self):
                pass

        class FakeSslContext:
            def wrap_socket(self, raw_socket, *, server_hostname):
                wrap_calls.append((raw_socket, server_hostname))
                return FakeTlsSocket()

        class FakeHttpsConnection:
            def __init__(self, host, port=None, timeout=None, context=None):
                self.host = host
                self.port = port
                self.timeout = timeout
                self.context = context
                self.sock = None
                self.requests = []
                connection_calls.append(self)

            def request(self, method, path, headers=None):
                self.requests.append((method, path, dict(headers or {})))

            def getresponse(self):
                return FakeUpstreamResponse(
                    headers={"Content-Type": "video/mp4"},
                    body=b"media",
                )

            def close(self):
                if self.sock:
                    self.sock.close()

        create_context = Mock(return_value=FakeSslContext())

        with (
            patch.object(media_security.socket, "socket", return_value=FakeRawSocket()),
            patch.object(
                media_security.socket,
                "getaddrinfo",
                side_effect=AssertionError("default transport performed a second DNS lookup"),
            ),
            patch.object(
                media_security,
                "ssl",
                SimpleNamespace(create_default_context=create_context),
                create=True,
            ),
            patch.object(
                media_security.http.client,
                "HTTPSConnection",
                FakeHttpsConnection,
            ),
        ):
            opened = media_security.open_video(
                "https://i0.hdslb.com/video.mp4?token=abc",
                resolver=resolver,
            )

        self.assertEqual([("i0.hdslb.com", 443)], resolver_calls)
        self.assertEqual([(PUBLIC_IP, 443)], connect_calls)
        create_context.assert_called_once_with()
        self.assertEqual("i0.hdslb.com", wrap_calls[0][1])
        self.assertEqual("i0.hdslb.com", connection_calls[0].host)
        self.assertEqual(
            "i0.hdslb.com",
            connection_calls[0].requests[0][2]["Host"],
        )
        self.assertEqual(
            "/video.mp4?token=abc",
            connection_calls[0].requests[0][1],
        )
        opened.close()

    def test_thumbnail_redirects_are_manual_and_revalidated_per_hop(self):
        media_security = load_media_security(self)
        resolved_hosts = []

        def resolver(host, port, *args, **kwargs):
            resolved_hosts.append(host)
            return public_resolver(host, port, *args, **kwargs)

        redirect = FakeUpstreamResponse(
            status=302,
            headers={"Location": "https://i1.hdslb.com/final.jpg"},
        )
        final = FakeUpstreamResponse(
            headers={"Content-Type": "image/jpeg", "Content-Length": "4"},
            body=b"jpeg",
        )
        opener = SequenceOpener([redirect, final])

        payload = media_security.fetch_thumbnail(
            "https://i0.hdslb.com/start.jpg",
            resolver=resolver,
            opener=opener,
        )

        self.assertEqual(b"jpeg", payload.content)
        self.assertEqual("image/jpeg", payload.content_type)
        self.assertEqual(["i0.hdslb.com", "i1.hdslb.com"], resolved_hosts)
        self.assertEqual(2, len(opener.calls))
        self.assertTrue(redirect.closed)

    def test_redirect_to_private_or_unlisted_host_is_rejected_before_request(self):
        media_security = load_media_security(self)
        redirect = FakeUpstreamResponse(
            status=302,
            headers={"Location": "https://127.0.0.1/internal"},
        )
        opener = SequenceOpener([redirect])

        with self.assertRaises(HTTPException):
            media_security.fetch_thumbnail(
                "https://i0.hdslb.com/start.jpg",
                resolver=public_resolver,
                opener=opener,
            )

        self.assertEqual(1, len(opener.calls))

    def test_rejects_more_than_three_redirect_hops(self):
        media_security = load_media_security(self)
        redirects = [
            FakeUpstreamResponse(
                status=302,
                headers={"Location": f"https://i0.hdslb.com/{index + 1}.jpg"},
            )
            for index in range(4)
        ]

        with self.assertRaises(HTTPException) as raised:
            media_security.fetch_thumbnail(
                "https://i0.hdslb.com/0.jpg",
                resolver=public_resolver,
                opener=SequenceOpener(redirects),
            )

        self.assertEqual(502, raised.exception.status_code)

    def test_thumbnail_accepts_only_safe_image_types_and_ten_mib(self):
        media_security = load_media_security(self)

        for content_type in (
            "text/html",
            "image/svg+xml",
            "application/octet-stream",
        ):
            with self.subTest(content_type=content_type):
                response = FakeUpstreamResponse(
                    headers={"Content-Type": content_type},
                    body=b"not-an-image",
                )
                with self.assertRaises(HTTPException) as raised:
                    media_security.fetch_thumbnail(
                        "https://i0.hdslb.com/image",
                        resolver=public_resolver,
                        opener=SequenceOpener([response]),
                    )
                self.assertEqual(415, raised.exception.status_code)

        too_large = FakeUpstreamResponse(
            headers={
                "Content-Type": "image/png",
                "Content-Length": str(10 * 1024 * 1024 + 1),
            },
        )
        with self.assertRaises(HTTPException) as raised:
            media_security.fetch_thumbnail(
                "https://i0.hdslb.com/image.png",
                resolver=public_resolver,
                opener=SequenceOpener([too_large]),
            )
        self.assertEqual(413, raised.exception.status_code)

    def test_video_accepts_media_and_octet_stream_but_rejects_html(self):
        media_security = load_media_security(self)

        for content_type in ("video/mp4", "audio/mp4", "application/octet-stream"):
            with self.subTest(content_type=content_type):
                response = FakeUpstreamResponse(
                    status=206,
                    headers={"Content-Type": content_type},
                    body=b"media",
                )
                opened = media_security.open_video(
                    "https://rr1---sn.googlevideo.com/media",
                    resolver=public_resolver,
                    opener=SequenceOpener([response]),
                )
                self.assertEqual(content_type, opened.content_type)
                opened.close()

        response = FakeUpstreamResponse(
            headers={"Content-Type": "text/html"},
            body=b"<html></html>",
        )
        with self.assertRaises(HTTPException) as raised:
            media_security.open_video(
                "https://rr1---sn.googlevideo.com/media",
                resolver=public_resolver,
                opener=SequenceOpener([response]),
            )
        self.assertEqual(415, raised.exception.status_code)


class MediaRouteHeaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_thumbnail_proxy_upgrades_http_url_before_secure_fetch(self):
        payload = SimpleNamespace(content=b"jpeg", content_type="image/jpeg")

        with patch.object(routes, "fetch_thumbnail", return_value=payload) as fetch:
            response = await routes.proxy_thumbnail(
                "http://i0.hdslb.com/bfs/archive/example.jpg?token=abc"
            )

        self.assertEqual(200, response.status_code)
        fetch.assert_called_once()
        self.assertEqual(
            "https://i0.hdslb.com/bfs/archive/example.jpg?token=abc",
            fetch.call_args.args[0],
        )

    async def test_video_proxy_uses_isolation_headers_without_wildcard_cors(self):
        upstream = FakeUpstreamResponse(
            status=206,
            headers={
                "Content-Type": "video/mp4",
                "Content-Length": "5",
                "Content-Range": "bytes 0-4/5",
            },
            body=b"media",
        )
        opened = type("Opened", (), {
            "response": upstream,
            "status": 206,
            "content_type": "video/mp4",
            "close": upstream.close,
        })()
        request = make_request(headers={"Range": "bytes=0-4"})

        with (
            patch.object(routes, "require_media_identity", return_value={"user_id": 1}),
            patch.object(routes, "open_video", return_value=opened, create=True),
            patch.object(routes.urllib.request, "urlopen", return_value=upstream),
            patch("api.security.socket.getaddrinfo", side_effect=public_resolver),
        ):
            response = await routes.proxy_video_stream(
                "https://rr1---sn.googlevideo.com/media",
                request,
            )

        self.assertNotIn("access-control-allow-origin", response.headers)
        self.assertEqual("nosniff", response.headers.get("x-content-type-options"))
        self.assertIn("default-src 'none'", response.headers.get("content-security-policy", ""))

    def test_global_cors_does_not_allow_wildcard_origin(self):
        with patch.dict(os.environ, {"CORS_ORIGINS": "*"}):
            import main
            main = importlib.reload(main)

        cors = next(
            middleware
            for middleware in main.app.user_middleware
            if middleware.cls.__name__ == "CORSMiddleware"
        )
        self.assertNotIn("*", cors.kwargs["allow_origins"])


if __name__ == "__main__":
    unittest.main()
