"""Bilibili request safety with fake upstreams and isolated persistent state."""

import io
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import yt_dlp
from yt_dlp.networking.common import Response

from core import bilibili, bilibili_guard as guard


API_URL = "https://api.bilibili.com/x/web-interface/nav"
CATALOG_URL = "https://api.bilibili.com/x/space/wbi/arc/search"
SUBTITLE_URL = "https://api.bilibili.com/x/player/v2"
VIDEO_URL = "https://api.bilibili.com/x/player/wbi/playurl"
CDN_URL = "https://aisubtitle.hdslb.com/subtitle.json"


@pytest.fixture(autouse=True)
def isolated_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "STATE_PATH", tmp_path / "guard.db")
    monkeypatch.setattr(guard, "_LOCK", threading.Lock())
    monkeypatch.setattr(guard, "_MEDIA_LOCK", threading.Lock())
    monkeypatch.setattr(guard, "LIMITS", {
        "api": (0, ((3600, 60), (86400, 300))),
        "media": (0, ((60, 120), (3600, 1200), (86400, 3000))),
    })
    monkeypatch.delenv("BILIBILI_USE_ACCOUNT_COOKIE", raising=False)


def upstream_response(status=200, payload=None, url=API_URL, headers=None):
    return httpx.Response(
        status, json=payload if payload is not None else {"code": 0, "data": {}},
        headers=headers, request=httpx.Request("GET", url),
    )


def test_http_429_blocks_every_subsequent_network_entry(monkeypatch):
    from core import platform_config, summarizer
    from core.blogger.catalog import BilibiliCatalogClient, CatalogError

    upstream = Mock(return_value=upstream_response(429, {}))
    monkeypatch.setattr(guard.httpx, "get", upstream)
    constructor = Mock()
    monkeypatch.setattr(yt_dlp, "YoutubeDL", constructor)
    monkeypatch.setattr(platform_config, "get_cookie", lambda platform: "SESSDATA=saved")

    with pytest.raises(guard.BilibiliAccessBlocked) as first:
        guard.guarded_get(API_URL)
    assert first.value.code == "rate_limit"
    for url in (API_URL, CDN_URL):
        with pytest.raises(guard.BilibiliAccessBlocked):
            guard.guarded_get(url)
    with pytest.raises(CatalogError) as catalog_error:
        BilibiliCatalogClient(cookie="").get("/x/space/wbi/arc/search")
    assert catalog_error.value.code == "rate_limit"
    with pytest.raises(guard.BilibiliAccessBlocked):
        summarizer._fetch_bilibili_json(API_URL, retries=10)
    with pytest.raises(guard.BilibiliAccessBlocked):
        with bilibili.youtube_dl({}, "https://www.bilibili.com/video/BV1test"):
            pytest.fail("The downloader must not be constructed while protection is active")
    validation = platform_config.validate("bilibili", "SESSDATA=draft")
    assert validation["status"] == "unknown"
    assert "受限" in validation["message"]
    constructor.assert_not_called()
    upstream.assert_called_once()


@pytest.mark.parametrize("status,payload", [
    (403, {}), (412, {}),
    (200, {"code": -111}), (200, {"code": -352}),
    (200, {"code": -401}), (200, {"code": -412}),
    (200, {"code": -509}), (200, {"code": -799}),
])
def test_catalog_risk_stops_catalog_while_subtitles_and_login_remain_available(
    monkeypatch, status, payload,
):
    from core import summarizer
    from core.blogger.catalog import BilibiliCatalogClient, CatalogError

    upstream = Mock(return_value=upstream_response(status, payload, CATALOG_URL))
    monkeypatch.setattr(guard.httpx, "get", upstream)
    client = BilibiliCatalogClient(cookie="")
    with pytest.raises(CatalogError) as first:
        client.get("/x/space/wbi/arc/search")
    assert first.value.code == "rate_limit"
    upstream.return_value = upstream_response(200, {"code": 0, "data": {"ok": 1}})
    with pytest.raises(CatalogError) as second:
        client.get("/x/space/wbi/arc/search")
    assert second.value.code == "rate_limit"
    upstream.assert_called_once()

    assert summarizer._fetch_bilibili_json(SUBTITLE_URL)["data"]["ok"] == 1
    assert guard.guarded_get(API_URL).status_code == 200
    for scope in ("all", "subtitle", "video", "media", "account"):
        guard.assert_allowed(scope)
    assert upstream.call_count == 3


@pytest.mark.parametrize("url,scope", [
    (CATALOG_URL, "catalog"), (SUBTITLE_URL, "subtitle"),
    (VIDEO_URL, "video"), (API_URL, "account"),
    ("https://upos-sz-mirror.bilivideo.com/video.m4s", "media"),
])
def test_http_412_blocks_only_the_affected_feature(monkeypatch, url, scope):
    upstream = Mock(return_value=upstream_response(412, {}, url))
    monkeypatch.setattr(guard.httpx, "get", upstream)
    with pytest.raises(guard.BilibiliAccessBlocked):
        guard.guarded_get(url)
    with pytest.raises(guard.BilibiliAccessBlocked):
        guard.guarded_get(url)
    for other in {"catalog", "subtitle", "video", "media", "account", "all"} - {scope}:
        guard.assert_allowed(other)
    upstream.assert_called_once()


def test_scoped_backoff_is_ten_twenty_forty_and_at_most_sixty_minutes(monkeypatch):
    now = [100_000.0]
    monkeypatch.setattr(guard.time, "time", lambda: now[0])
    for seconds in (600, 1200, 2400, 3600, 3600):
        with pytest.raises(guard.BilibiliAccessBlocked):
            guard.check_response(200, {"code": -352}, scope="catalog")
        now[0] += seconds - 1
        with pytest.raises(guard.BilibiliAccessBlocked):
            guard.assert_allowed("catalog")
        guard.assert_allowed("subtitle")
        now[0] += 1
        guard.assert_allowed("catalog")


def test_expiry_allows_manual_request_without_sending_any_automatic_request(monkeypatch):
    now = [100_000.0]
    monkeypatch.setattr(guard.time, "time", lambda: now[0])
    upstream = Mock(return_value=upstream_response(412, {}, CATALOG_URL))
    monkeypatch.setattr(guard.httpx, "get", upstream)
    with pytest.raises(guard.BilibiliAccessBlocked):
        guard.guarded_get(CATALOG_URL)
    now[0] += 600
    guard.assert_allowed("catalog")
    upstream.assert_called_once()
    upstream.return_value = upstream_response(200, {"code": 0, "data": {}}, CATALOG_URL)
    assert guard.guarded_get(CATALOG_URL).status_code == 200
    assert upstream.call_count == 2

    # One successful response must not let alternating success/risk responses
    # avoid the increasing cooldown for repeated platform refusals.
    upstream.return_value = upstream_response(412, {}, CATALOG_URL)
    with pytest.raises(guard.BilibiliAccessBlocked):
        guard.guarded_get(CATALOG_URL)
    now[0] += 1199
    with pytest.raises(guard.BilibiliAccessBlocked):
        guard.assert_allowed("catalog")
    now[0] += 1
    guard.assert_allowed("catalog")
    assert upstream.call_count == 3


def test_old_risk_history_resets_backoff_without_blocking_for_a_day(monkeypatch):
    now = [100_000.0]
    monkeypatch.setattr(guard.time, "time", lambda: now[0])
    upstream = Mock()
    monkeypatch.setattr(guard.httpx, "get", upstream)
    guard.trip("第一次限制", "catalog")
    now[0] += 600
    guard.trip("再次限制", "catalog")
    now[0] += 1200
    guard.assert_allowed("catalog")
    now[0] += 86401
    guard.trip("一天后新的限制", "catalog")
    now[0] += 599
    with pytest.raises(guard.BilibiliAccessBlocked):
        guard.assert_allowed("catalog")
    now[0] += 1
    guard.assert_allowed("catalog")
    upstream.assert_not_called()


@pytest.mark.parametrize("age", [120, 1200])
def test_legacy_daylong_pause_migrates_from_original_trigger_without_extension(monkeypatch, age):
    now = [100_000.0]
    monkeypatch.setattr(guard.time, "time", lambda: now[0])
    with sqlite3.connect(guard.STATE_PATH) as connection:
        connection.execute(
            "CREATE TABLE protection (id INTEGER PRIMARY KEY CHECK(id=1), blocked_until REAL NOT NULL, reason TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO protection VALUES (1, ?, ?)", (now[0] - age + 86400, "历史平台限制"))

    remaining = 600 - age
    if remaining > 0:
        with pytest.raises(guard.BilibiliAccessBlocked):
            guard.assert_allowed("catalog")
        # A second database open must not restart or extend the cooldown.
        now[0] += remaining - 1
        with pytest.raises(guard.BilibiliAccessBlocked):
            guard.assert_allowed("catalog")
        now[0] += 1
    guard.assert_allowed("catalog")
    guard.assert_allowed("subtitle")


def test_circuit_breaker_survives_a_new_process():
    guard.trip("测试风控")
    environment = os.environ.copy()
    environment["BILIBILI_GUARD_PATH"] = str(guard.STATE_PATH)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run(
        [sys.executable, "-B", "-c", """
from core.bilibili_guard import assert_allowed, BilibiliAccessBlocked
try:
    assert_allowed()
except BilibiliAccessBlocked as error:
    print(error.code)
else:
    raise SystemExit('Persistent circuit breaker was lost')
"""],
        env=environment, capture_output=True, text=True, timeout=10, check=True,
    )
    assert result.stdout.strip() == "rate_limit"


def test_restart_does_not_reset_request_budget():
    now = time.time()
    with guard._database() as connection:
        connection.executemany("INSERT INTO requests VALUES (?, 'api')", [(now,)] * 60)
    environment = os.environ.copy()
    environment["BILIBILI_GUARD_PATH"] = str(guard.STATE_PATH)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run(
        [sys.executable, "-B", "-c", """
from core import bilibili_guard as guard
guard.LIMITS['api'] = (0, ((3600, 60), (86400, 300)))
try:
    with guard.request_slot():
        raise SystemExit('Persistent request budget was lost')
except guard.BilibiliAccessBlocked as error:
    print(error.code)
"""],
        env=environment, capture_output=True, text=True, timeout=10, check=True,
    )
    assert result.stdout.strip() == "budget"


@pytest.mark.parametrize("kind", ["api", "media"])
def test_separate_worker_processes_share_one_request_budget(kind):
    with guard._database() as connection:
        connection.executemany("INSERT INTO requests VALUES (?, ?)", [(time.time(), kind)] * 58)
    environment = os.environ.copy()
    environment["BILIBILI_GUARD_PATH"] = str(guard.STATE_PATH)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    script = f"""
from core import bilibili_guard as guard
guard.LIMITS[{kind!r}] = (0, ((3600, 60), (86400, 300)))
try:
    with guard.request_slot({kind!r}):
        print('admitted')
except guard.BilibiliAccessBlocked as error:
    print(error.code)
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-B", "-c", script], env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for _ in range(4)
    ]
    try:
        outputs = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=10)
            assert process.returncode == 0, stderr
            outputs.append(stdout.strip())
        assert sorted(outputs) == ["admitted", "admitted", "budget", "budget"]
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
    with sqlite3.connect(guard.STATE_PATH) as connection:
        assert connection.execute("SELECT count(*) FROM requests").fetchone()[0] == 60


@pytest.mark.parametrize("kind,interval", [("api", 5), ("media", 0.25)])
def test_requests_keep_their_minimum_interval(monkeypatch, kind, interval):
    now = [100_000.0]
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(guard.time, "time", lambda: now[0])
    monkeypatch.setattr(guard.time, "sleep", sleep)
    monkeypatch.setitem(guard.LIMITS, kind, (interval, ((3600, 120), (86400, 600))))
    admitted = []
    for _ in range(3):
        with guard.request_slot(kind):
            admitted.append(now[0])
    assert admitted == [100_000.0, 100_000.0 + interval, 100_000.0 + 2 * interval]
    assert waits == [interval, interval]


@pytest.mark.parametrize("kind", ["api", "media"])
def test_protection_is_rechecked_after_waiting(monkeypatch, kind):
    now = [100_000.0]
    monkeypatch.setattr(guard.time, "time", lambda: now[0])
    monkeypatch.setitem(guard.LIMITS, kind, (10, ((3600, 60),)))
    with guard.request_slot(kind):
        pass

    def risk_during_wait(seconds):
        now[0] += seconds
        guard.trip("另一请求已触发风控")

    monkeypatch.setattr(guard.time, "sleep", risk_during_wait)
    with pytest.raises(guard.BilibiliAccessBlocked):
        with guard.request_slot(kind):
            pytest.fail("A waiting request must stop when protection was enabled")


@pytest.mark.parametrize("blocked_stage", ["rate_wait", "network"])
def test_subtitle_cdn_completes_while_api_is_waiting(monkeypatch, blocked_stage):
    """Exercise both blocking regions with real concurrent request threads."""
    api_blocked = threading.Event()
    release_api = threading.Event()
    now = [100_000.0]
    monkeypatch.setattr(guard.time, "time", lambda: now[0])

    def block_api():
        api_blocked.set()
        assert release_api.wait(3), "test did not release the API request"

    def sleep(seconds):
        block_api()
        now[0] += seconds

    if blocked_stage == "rate_wait":
        monkeypatch.setitem(guard.LIMITS, "api", (5, ((3600, 120), (86400, 600))))
        with guard.request_slot("api", "metadata"):
            pass
        monkeypatch.setattr(guard.time, "sleep", sleep)

    def upstream(url, **kwargs):
        if url == API_URL and blocked_stage == "network":
            block_api()
        return upstream_response(url=url)

    monkeypatch.setattr(guard.httpx, "get", upstream)
    with ThreadPoolExecutor(max_workers=2) as executor:
        api = executor.submit(guard.guarded_get, API_URL)
        try:
            assert api_blocked.wait(2)
            media = executor.submit(guard.guarded_get, CDN_URL)
            assert media.result(timeout=1).status_code == 200
            assert not api.done(), "CDN should finish before API is released"
        finally:
            release_api.set()
        assert api.result(timeout=2).status_code == 200


def test_subtitle_cdn_does_not_wait_for_api_in_another_process():
    environment = os.environ.copy()
    environment["BILIBILI_GUARD_PATH"] = str(guard.STATE_PATH)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    # The parent holds API's process lock across the child's whole lifetime.
    # Independent thread locks alone cannot make this scenario pass.
    with guard.request_slot("api", "metadata"):
        result = subprocess.run(
            [sys.executable, "-B", "-c", """
from core.bilibili_guard import request_slot
with request_slot('media', 'subtitle'):
    print('admitted')
"""],
            env=environment, capture_output=True, text=True, timeout=5, check=True,
        )
    assert result.stdout.strip() == "admitted"
    with sqlite3.connect(guard.STATE_PATH) as connection:
        assert dict(connection.execute("SELECT kind, count(*) FROM requests GROUP BY kind")) == {"api": 1, "media": 1}


def test_request_timing_logs_do_not_include_signed_urls_or_credentials(monkeypatch, caplog):
    url = CDN_URL + "?sign=private-signature"
    monkeypatch.setattr(guard.httpx, "get", Mock(return_value=upstream_response(url=url)))
    with caplog.at_level("INFO", logger="core.bilibili_guard"):
        guard.guarded_get(url, headers={"Cookie": "SESSDATA=private-cookie"})
    message = caplog.records[-1].getMessage()
    assert "kind=media scope=subtitle" in message
    for field in ("lock_wait_ms=", "rate_wait_ms=", "active_ms=", "outcome=completed"):
        assert field in message
    assert "private" not in message
    assert "https://" not in message


@pytest.mark.parametrize("earlier_requests,age,expected_total", [
    (58, 0, 60),
    (298, 7200, 300),
])
def test_hourly_and_daily_budgets_cannot_be_overspent_concurrently(
    monkeypatch, earlier_requests, age, expected_total,
):
    now = 100_000.0
    monkeypatch.setattr(guard.time, "time", lambda: now)
    with guard._database() as connection:
        connection.executemany(
            "INSERT INTO requests VALUES (?, 'api')", [(now - age,)] * earlier_requests,
        )

    def admit(_):
        try:
            with guard.request_slot():
                return True
        except guard.BilibiliAccessBlocked as error:
            assert error.code == "budget"
            return False

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(admit, range(8)))
    assert sum(results) == 2
    with sqlite3.connect(guard.STATE_PATH) as connection:
        assert connection.execute("SELECT count(*) FROM requests").fetchone()[0] == expected_total


def test_cookie_and_authorization_never_go_to_subtitle_cdn(monkeypatch):
    upstream = Mock(return_value=upstream_response(url=CDN_URL))
    monkeypatch.setattr(guard.httpx, "get", upstream)
    guard.guarded_get(CDN_URL, headers={
        "cOoKiE": "SESSDATA=private", "AUTHORIZATION": "Bearer private", "Referer": API_URL,
    })
    sent_headers = {name.lower(): value for name, value in upstream.call_args.kwargs["headers"].items()}
    assert sent_headers == {"referer": API_URL}


def test_redirects_cannot_forward_account_credentials(monkeypatch):
    response = upstream_response(302, {}, headers={"Location": CDN_URL})
    upstream = Mock(return_value=response)
    monkeypatch.setattr(guard.httpx, "get", upstream)
    assert guard.guarded_get(API_URL, headers={"Cookie": "SESSDATA=private"}, follow_redirects=True) is response
    assert upstream.call_args.kwargs["follow_redirects"] is False
    upstream.assert_called_once()


def test_expired_media_403_stops_request_without_claiming_account_risk(monkeypatch):
    upstream = Mock(side_effect=[upstream_response(403, {}, CDN_URL), upstream_response()])
    monkeypatch.setattr(guard.httpx, "get", upstream)
    with pytest.raises(guard.BilibiliAccessBlocked) as blocked:
        guard.guarded_get(CDN_URL)
    assert blocked.value.code == "protection"
    assert "媒体链接" in str(blocked.value)
    guard.assert_allowed()
    assert guard.guarded_get(API_URL).status_code == 200
    assert upstream.call_count == 2


def fake_youtube_dl(monkeypatch, body, status=200, url=API_URL):
    stream = io.BytesIO(body)
    response = Response(stream, url, {"Content-Type": "application/json"}, status)
    opener = Mock(return_value=response)

    class Downloader:
        def build_request_director(self, handlers):
            return Mock()

        def dl(self, *args, **kwargs):
            raise AssertionError("Unexpected network download")

        def __init__(self, options):
            self.urlopen = opener

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Downloader)
    return opener, stream


def test_ytdlp_api_risk_payload_blocks_fallback_requests(monkeypatch):
    opener, stream = fake_youtube_dl(monkeypatch, b'{"code":-352,"message":"risk"}', url=VIDEO_URL)
    with bilibili.youtube_dl({}, "https://www.bilibili.com/video/BV1test") as downloader:
        with pytest.raises(guard.BilibiliAccessBlocked):
            downloader.urlopen(VIDEO_URL)
        with pytest.raises(guard.BilibiliAccessBlocked):
            downloader.urlopen("https://api.bilibili.com/x/web-interface/view")
    opener.assert_called_once()
    assert stream.closed
    with pytest.raises(guard.BilibiliAccessBlocked):
        guard.assert_allowed(guard.request_scope(VIDEO_URL))
    guard.assert_allowed("subtitle")


def test_ytdlp_normal_json_response_is_preserved_byte_for_byte(monkeypatch):
    body = json.dumps({"code": 0, "data": {"title": "字幕保留", "count": 42}}, ensure_ascii=False).encode()
    opener, stream = fake_youtube_dl(monkeypatch, body)
    with bilibili.youtube_dl({}, "https://www.bilibili.com/video/BV1test") as downloader:
        with downloader.urlopen(API_URL) as response:
            assert response.status == 200
            assert response.url == API_URL
            assert response.headers["Content-Type"] == "application/json"
            assert response.read(7) + response.read() == body
    assert stream.closed
    opener.assert_called_once()


def test_unavailable_state_fails_closed(monkeypatch, tmp_path):
    invalid_parent = tmp_path / "not-a-directory"
    invalid_parent.write_text("file")
    monkeypatch.setattr(guard, "STATE_PATH", invalid_parent / "guard.db")
    upstream = Mock()
    monkeypatch.setattr(guard.httpx, "get", upstream)
    with pytest.raises(guard.BilibiliAccessBlocked):
        guard.guarded_get(API_URL)
    upstream.assert_not_called()


def test_thumbnail_429_does_not_pause_subtitle_api_and_honors_retry_after(monkeypatch):
    now = [100000.0]
    monkeypatch.setattr(guard.time, 'time', lambda: now[0])
    with pytest.raises(guard.BilibiliAccessBlocked):
        guard.check_response(429, kind='media', scope='thumbnail', retry_after='300')
    guard.assert_allowed('subtitle')
    guard.assert_allowed('metadata')
    with pytest.raises(guard.BilibiliAccessBlocked):
        guard.assert_allowed('thumbnail')
    now[0] += 299
    with pytest.raises(guard.BilibiliAccessBlocked):
        guard.assert_allowed('thumbnail')
    now[0] += 1
    guard.assert_allowed('thumbnail')


def test_thumbnail_backoff_is_two_four_eight_then_ten_minutes(monkeypatch):
    now = [100000.0]
    monkeypatch.setattr(guard.time, 'time', lambda: now[0])
    for delay in [120, 240, 480, 600]:
        with pytest.raises(guard.BilibiliAccessBlocked):
            guard.check_response(429, kind='media', scope='thumbnail')
        now[0] += delay
        guard.assert_allowed('thumbnail')
