"""Exercise yt-dlp's real urllib redirect machinery with fake HTTP I/O."""

import io
import sqlite3
import urllib.response
from email.message import Message
from http import HTTPStatus
from pathlib import Path
from unittest.mock import Mock

import pytest
import yt_dlp
from yt_dlp.networking import _urllib
from yt_dlp.networking import Request
from yt_dlp.networking.exceptions import HTTPError

from core.bilibili_transport import install_single_hop_transport
from core import bilibili, bilibili_guard as guard


def fake_http(monkeypatch, status=302):
    calls = []

    def open_response(handler, request):
        calls.append(request.full_url)
        headers = Message()
        headers["Content-Type"] = "text/plain"
        first = request.full_url.endswith("/start")
        response_status = status if first else 200
        if first:
            headers["Location"] = "https://redirect.invalid/final"
        response = urllib.response.addinfourl(
            io.BytesIO(b"response"), headers, request.full_url, response_status,
        )
        response.msg = HTTPStatus(response_status).phrase
        return response

    monkeypatch.setattr(_urllib.HTTPHandler, "https_open", open_response)
    return calls


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_transport_never_follows_even_the_first_redirect(monkeypatch, status):
    calls = fake_http(monkeypatch, status)
    with yt_dlp.YoutubeDL({"quiet": True, "proxy": ""}) as downloader:
        install_single_hop_transport(downloader)
        with pytest.raises(HTTPError) as raised:
            downloader.urlopen("https://source.invalid/start")
        error = raised.value
        assert error.status == status
        assert error.response.headers["Location"] == "https://redirect.invalid/final"
        error.close()
    assert calls == ["https://source.invalid/start"]


def test_transport_keeps_success_body_and_cookie_jar(monkeypatch):
    calls = fake_http(monkeypatch)
    with yt_dlp.YoutubeDL({"quiet": True, "proxy": ""}) as downloader:
        cookiejar = downloader.cookiejar
        install_single_hop_transport(downloader)
        handler, = downloader._request_director.handlers.values()
        assert handler.cookiejar is cookiejar
        with downloader.urlopen("https://source.invalid/final") as response:
            assert response.status == 200
            assert response.read() == b"response"
    assert calls == ["https://source.invalid/final"]


def test_installation_closes_previous_director_without_global_patch(monkeypatch):
    calls = fake_http(monkeypatch)
    with yt_dlp.YoutubeDL({"quiet": True, "proxy": ""}) as downloader:
        previous = downloader._request_director
        close = Mock(wraps=previous.close)
        monkeypatch.setattr(previous, "close", close)
        install_single_hop_transport(downloader)
        close.assert_called_once()
        assert previous.handlers == {}

    # An independently created urllib transport still follows redirects.
    with yt_dlp.YoutubeDL({"quiet": True, "proxy": ""}) as ordinary:
        ordinary._request_director = ordinary.build_request_director([_urllib.UrllibRH])
        with ordinary.urlopen("https://source.invalid/start") as response:
            assert response.url == "https://redirect.invalid/final"
    assert calls == ["https://source.invalid/start", "https://redirect.invalid/final"]


def fake_http_sequence(monkeypatch, replies):
    """Mock only socket I/O; keep YoutubeDL, cookies, errors and redirects real."""
    requests = []
    bodies = []

    def open_response(handler, request):
        requests.append({
            "url": request.full_url,
            "headers": {name.lower(): value for name, value in request.header_items()},
        })
        assert len(requests) <= len(replies), "unexpected extra network request"
        status, reply_headers, body = replies[len(requests) - 1]
        headers = Message()
        for name, value in reply_headers.items():
            headers[name] = value
        stream = io.BytesIO(body)
        bodies.append(stream)
        response = urllib.response.addinfourl(stream, headers, request.full_url, status)
        response.msg = HTTPStatus(status).phrase
        return response

    monkeypatch.setattr(_urllib.HTTPHandler, "https_open", open_response)
    monkeypatch.setattr(_urllib.HTTPHandler, "http_open", open_response)
    return requests, bodies


def test_wrapper_blocks_external_redirect_into_bilibili_during_protection(monkeypatch):
    requests, bodies = fake_http_sequence(monkeypatch, [
        (302, {"Location": "https://api.bilibili.com/x/web-interface/nav"}, b""),
    ])
    guard.trip("test")
    with bilibili.youtube_dl({"quiet": True, "proxy": ""}, "https://external.invalid/start") as downloader:
        with pytest.raises(guard.BilibiliAccessBlocked):
            downloader.urlopen("https://external.invalid/start")
    assert [request["url"] for request in requests] == ["https://external.invalid/start"]
    assert bodies[0].closed


def test_wrapper_accounts_for_each_redirect_hop(monkeypatch):
    requests, bodies = fake_http_sequence(monkeypatch, [
        (302, {"Location": "https://api.bilibili.com/x/test"}, b""),
        (302, {"Location": "https://i0.hdslb.com/final"}, b""),
        (200, {"Content-Type": "text/plain"}, b"done"),
    ])
    with bilibili.youtube_dl({"quiet": True, "proxy": ""}, "https://www.bilibili.com/start") as downloader:
        with downloader.urlopen("https://www.bilibili.com/start") as response:
            assert response.read() == b"done"
    assert len(requests) == 3
    assert all(body.closed for body in bodies)
    with sqlite3.connect(guard.STATE_PATH) as connection:
        assert dict(connection.execute("SELECT kind, count(*) FROM requests GROUP BY kind")) == {
            "api": 2, "media": 1,
        }


def test_wrapper_removes_explicit_credentials_on_cross_host_redirect(monkeypatch):
    monkeypatch.setenv("BILIBILI_USE_ACCOUNT_COOKIE", "true")
    monkeypatch.setenv("BILIBILI_COOKIE_SCOPE", "all")
    monkeypatch.setattr("core.platform_config.get_cookie", lambda platform: "SESSDATA=private")
    requests, _ = fake_http_sequence(monkeypatch, [
        (302, {"Location": "https://aisubtitle.hdslb.com/final"}, b""),
        (200, {"Content-Type": "text/plain"}, b"done"),
    ])
    request = Request("https://www.bilibili.com/start", headers={
        "Cookie": "SESSDATA=private", "Authorization": "Bearer private",
    })
    with bilibili.youtube_dl({"quiet": True, "proxy": ""}, request.url) as downloader:
        with downloader.urlopen(request) as response:
            assert response.read() == b"done"
    assert requests[0]["headers"]["cookie"] == "SESSDATA=private"
    assert "cookie" not in requests[1]["headers"]
    assert "authorization" not in requests[1]["headers"]
    # The caller's reusable request is not mutated by redirect processing.
    assert request.headers["Cookie"] == "SESSDATA=private"


def test_wrapper_stops_before_seventh_request(monkeypatch):
    requests, bodies = fake_http_sequence(monkeypatch, [
        (302, {"Location": f"https://www.bilibili.com/hop/{index + 1}"}, b"")
        for index in range(6)
    ])
    with bilibili.youtube_dl({"quiet": True, "proxy": ""}, "https://www.bilibili.com/start") as downloader:
        with pytest.raises(guard.BilibiliAccessBlocked, match="重定向"):
            downloader.urlopen("https://www.bilibili.com/start")
    assert len(requests) == 6
    assert all(body.closed for body in bodies)
    with sqlite3.connect(guard.STATE_PATH) as connection:
        assert connection.execute("SELECT count(*) FROM requests").fetchone()[0] == 6


@pytest.mark.parametrize("status", [403, 412, 429])
def test_wrapper_closes_real_http_error_response_and_blocks_next_request(monkeypatch, status):
    requests, bodies = fake_http_sequence(monkeypatch, [(status, {}, b"blocked")])
    with bilibili.youtube_dl({"quiet": True, "proxy": ""}, "https://www.bilibili.com/start") as downloader:
        for _ in range(2):
            with pytest.raises(guard.BilibiliAccessBlocked):
                downloader.urlopen("https://www.bilibili.com/start")
    assert len(requests) == 1
    assert bodies[0].closed


@pytest.mark.parametrize("protocol", ["m3u8", "m3u8_native", "rtmp"])
def test_wrapper_rejects_formats_that_may_delegate_network_to_ffmpeg(monkeypatch, tmp_path, protocol):
    underlying_download = Mock(side_effect=AssertionError("unguarded downloader invoked"))
    monkeypatch.setattr(yt_dlp.YoutubeDL, "dl", underlying_download)
    with bilibili.youtube_dl({"quiet": True, "proxy": ""}, "https://www.bilibili.com/video/BV1test") as downloader:
        with pytest.raises(guard.BilibiliAccessBlocked, match="官方客户端"):
            downloader.dl(str(tmp_path / "video.mp4"), {
                "url": "https://video.bilivideo.com/video.m3u8", "protocol": protocol,
            })
    underlying_download.assert_not_called()


@pytest.mark.parametrize("details", [
    {"protocol": "http_dash_segments", "is_live": True},
    {"protocol": "https", "section_start": 0},
    {"protocol": "https", "section_end": 30},
    {"requested_formats": [{
        "url": "https://video.bilivideo.com/video", "protocol": "http_dash_segments", "is_live": True,
    }]},
])
def test_wrapper_rejects_live_or_partial_downloads_that_select_ffmpeg(monkeypatch, tmp_path, details):
    underlying_download = Mock(side_effect=AssertionError("unguarded downloader invoked"))
    monkeypatch.setattr(yt_dlp.YoutubeDL, "dl", underlying_download)
    with bilibili.youtube_dl({"quiet": True, "proxy": ""}, "https://www.bilibili.com/video/BV1test") as downloader:
        with pytest.raises(guard.BilibiliAccessBlocked):
            downloader.dl(str(tmp_path / "video.mp4"), {
                "url": "https://video.bilivideo.com/video", **details,
            })
    underlying_download.assert_not_called()


@pytest.mark.parametrize("protocol", ["https", "http_dash_segments"])
def test_wrapper_retains_native_recorded_video_downloads(monkeypatch, tmp_path, protocol):
    underlying_download = Mock(return_value=(True, True))
    monkeypatch.setattr(yt_dlp.YoutubeDL, "dl", underlying_download)
    with bilibili.youtube_dl({"quiet": True, "proxy": ""}, "https://www.bilibili.com/video/BV1test") as downloader:
        assert downloader.dl(str(tmp_path / "video.mp4"), {
            "url": "https://video.bilivideo.com/video", "protocol": protocol,
        }) == (True, True)
    underlying_download.assert_called_once()


@pytest.fixture
def configured_metadata_cookie(monkeypatch):
    monkeypatch.setenv("BILIBILI_USE_ACCOUNT_COOKIE", "true")
    monkeypatch.setenv("BILIBILI_COOKIE_SCOPE", "metadata")
    monkeypatch.setattr("core.platform_config.get_cookie", lambda platform: "SESSDATA=unit-test; bili_jct=csrf-test")
    monkeypatch.setattr(bilibili, "_cookiefile_path", None)
    monkeypatch.setattr(bilibili, "_cookiefile_value", None)


def test_wrapper_sends_configured_cookie_only_to_required_metadata_apis(monkeypatch, configured_metadata_cookie):
    urls = [
        "https://www.bilibili.com/video/BV1test",
        "https://api.bilibili.com/x/web-interface/view?bvid=BV1test",
        "https://api.bilibili.com/x/player/pagelist?bvid=BV1test",
        "https://api.bilibili.com/x/player/wbi/playurl?bvid=BV1test",
        "https://api.bilibili.com/x/web-interface/nav",
        "https://api.bilibili.com/x/space/wbi/arc/search?mid=1",
        "https://api.bilibili.com/x/player/v2?bvid=BV1test&cid=1",
        "https://api.bilibili.com/x/player/wbi/v2?bvid=BV1test&cid=1",
        "https://api.bilibili.com/x/v2/dm/view?oid=1",
        "https://aisubtitle.hdslb.com/subtitle.json",
    ]
    requests, _ = fake_http_sequence(monkeypatch, [
        (200, {"Content-Type": "application/json"}, b'{"code":0,"data":{}}')
        for _ in urls
    ])
    options = {**bilibili.ydl_opts_for(urls[0]), "proxy": "", "quiet": True}
    cookiefile = Path(options["cookiefile"])
    with bilibili.youtube_dl(options, urls[0]) as downloader:
        for url in urls:
            with downloader.urlopen(url) as response:
                assert response.status == 200
    for index, request in enumerate(requests):
        if index in (1, 2) or 4 <= index <= 8:
            assert request["headers"]["cookie"] == "SESSDATA=unit-test; bili_jct=csrf-test"
        else:
            assert "cookie" not in request["headers"]
    assert "SESSDATA" not in cookiefile.read_text()


@pytest.mark.parametrize("target", [
    "https://api.bilibili.com/x/player/playurl?bvid=BV1test",
    "https://aisubtitle.hdslb.com/subtitle.json",
])
def test_wrapper_rechecks_credential_scope_on_every_redirect(monkeypatch, configured_metadata_cookie, target):
    requests, _ = fake_http_sequence(monkeypatch, [
        (302, {"Location": target}, b""),
        (200, {"Content-Type": "application/json"}, b'{"code":0,"data":{}}'),
    ])
    url = "https://api.bilibili.com/x/player/v2?bvid=BV1test&cid=1"
    with bilibili.youtube_dl({"quiet": True, "proxy": ""}, url) as downloader:
        with downloader.urlopen(url) as response:
            assert response.status == 200
    assert requests[0]["headers"]["cookie"] == "SESSDATA=unit-test; bili_jct=csrf-test"
    assert "cookie" not in requests[1]["headers"]


def test_wrapper_rejects_https_to_http_before_sending_account_cookie(monkeypatch, configured_metadata_cookie):
    requests, bodies = fake_http_sequence(monkeypatch, [
        (302, {"Location": "http://api.bilibili.com/x/player/v2?bvid=BV1test&cid=1"}, b""),
    ])
    url = "https://api.bilibili.com/x/player/v2?bvid=BV1test&cid=1"
    with bilibili.youtube_dl({"quiet": True, "proxy": ""}, url) as downloader:
        with pytest.raises(guard.BilibiliAccessBlocked, match="非加密"):
            downloader.urlopen(url)
    assert len(requests) == 1
    assert bodies[0].closed


def test_metadata_cookie_cannot_be_persisted_or_widened_by_upstream_set_cookie(monkeypatch, configured_metadata_cookie):
    requests, _ = fake_http_sequence(monkeypatch, [
        (200, {"Content-Type": "application/json", "Set-Cookie": "SESSDATA=upstream-test; Domain=.bilibili.com; Path=/; Secure"}, b'{"code":0,"data":{}}'),
        (200, {"Content-Type": "text/plain"}, b"video page"),
    ])
    source = "https://www.bilibili.com/video/BV1test"
    options = {**bilibili.ydl_opts_for(source), "quiet": True, "proxy": ""}
    with bilibili.youtube_dl(options, source) as downloader:
        with downloader.urlopen("https://api.bilibili.com/x/web-interface/nav") as response:
            assert response.status == 200
        with downloader.urlopen(source) as response:
            assert response.status == 200
    assert "cookie" not in requests[1]["headers"]
    assert "SESSDATA" not in Path(options["cookiefile"]).read_text()


def test_explicit_all_scope_allows_authenticated_video_page_without_cdn_cookie(monkeypatch, configured_metadata_cookie):
    monkeypatch.setenv("BILIBILI_COOKIE_SCOPE", "all")
    requests, _ = fake_http_sequence(monkeypatch, [
        (200, {"Content-Type": "text/plain"}, b"video page"),
        (200, {"Content-Type": "video/mp4"}, b"video"),
    ])
    source = "https://www.bilibili.com/video/BV1test"
    options = {**bilibili.ydl_opts_for(source), "quiet": True, "proxy": ""}
    with bilibili.youtube_dl(options, source) as downloader:
        with downloader.urlopen(source) as response:
            assert response.read() == b"video page"
        with downloader.urlopen("https://video.bilivideo.com/video.m4s") as response:
            assert response.read() == b"video"
    assert requests[0]["headers"]["cookie"] == "SESSDATA=unit-test; bili_jct=csrf-test"
    assert "cookie" not in requests[1]["headers"]
    assert "SESSDATA" in Path(options["cookiefile"]).read_text()
