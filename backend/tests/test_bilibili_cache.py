"""Successful JSON caching must reduce requests without bypassing protection."""

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import httpx
import pytest

from core import bilibili_cache as cache, bilibili_guard as guard


URL = "https://api.bilibili.com/x/player/v2"


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def response(payload=None, *, status=200, content=None):
    options = {"content": content} if content is not None else {"json": payload or {"code": 0, "data": {"title": "字幕"}}}
    return httpx.Response(status, request=httpx.Request("GET", URL), **options)


def test_cache_hit_reuses_json_and_does_not_make_another_request(monkeypatch):
    upstream = Mock(return_value=response())
    monkeypatch.setattr(cache, "guarded_get", upstream)
    first = cache.cached_get(URL, params={"bvid": "BV1test"})
    second = cache.cached_get(URL, params={"bvid": "BV1test"})
    assert first.json() == second.json() == {"code": 0, "data": {"title": "字幕"}}
    assert second.status_code == 200
    assert str(second.request.url) == URL + "?bvid=BV1test"
    upstream.assert_called_once()
    first.json()["data"]["title"] = "caller mutation"
    assert cache.cached_get(URL, params={"bvid": "BV1test"}).json()["data"]["title"] == "字幕"


def test_subtitle_body_without_code_is_cacheable(monkeypatch):
    payload = {"body": [{"from": 0, "to": 2, "content": "合法字幕"}]}
    upstream = Mock(return_value=response(payload))
    monkeypatch.setattr(cache, "guarded_get", upstream)
    assert cache.cached_get(URL).json() == payload
    assert cache.cached_get(URL).json() == payload
    upstream.assert_called_once()


def test_cookie_and_parameters_isolate_cached_responses(monkeypatch):
    upstream = Mock(side_effect=lambda url, **kwargs: response({"code": 0, "data": {"n": upstream.call_count}}))
    monkeypatch.setattr(cache, "guarded_get", upstream)
    first = cache.cached_get(URL, headers={"Cookie": "SESSDATA=first"}, params={"cid": 1}).json()
    second = cache.cached_get(URL, headers={"cookie": "SESSDATA=second"}, params={"cid": 1}).json()
    third = cache.cached_get(URL, headers={"Cookie": "SESSDATA=first"}, params={"cid": 2}).json()
    assert len({first["data"]["n"], second["data"]["n"], third["data"]["n"]}) == 3
    assert cache.cached_get(URL, headers={"cookie": "SESSDATA=first"}, params={"cid": 1}).json() == first
    assert upstream.call_count == 3
    assert all("SESSDATA" not in key and "first" not in key and "second" not in key for key in cache._entries)


def test_cookie_jar_and_dynamic_auth_are_not_shared(monkeypatch):
    upstream = Mock(return_value=response())
    monkeypatch.setattr(cache, "guarded_get", upstream)
    cache.cached_get(URL, cookies={"SESSDATA": "first"})
    cache.cached_get(URL, cookies={"SESSDATA": "second"})
    assert upstream.call_count == 2
    auth = httpx.BasicAuth("user", "secret")
    cache.cached_get(URL, auth=auth)
    cache.cached_get(URL, auth=auth)
    assert upstream.call_count == 4


def test_catalog_signature_changes_reuse_cache_without_changing_outbound_parameters(monkeypatch):
    url = "https://api.bilibili.com/x/space/wbi/arc/search"
    params = {"mid": "123", "pn": "1", "ps": "30", "order": "pubdate", "wts": "100", "w_rid": "old"}
    headers = {"Cookie": "SESSDATA=private"}
    upstream = Mock(return_value=response())
    monkeypatch.setattr(cache, "guarded_get", upstream)
    cache.cached_get(url, params=params, headers=headers)
    updated = {**params, "wts": "200", "w_rid": "new"}
    hit = cache.cached_get(url, params=updated, headers=headers)
    upstream.assert_called_once_with(url, params=params, headers=headers)
    assert params["wts"] == "100" and params["w_rid"] == "old"
    assert hit.request.url.params["wts"] == "200"
    assert hit.request.url.params["w_rid"] == "new"
    assert hit.json() == {"code": 0, "data": {"title": "字幕"}}


@pytest.mark.parametrize("changed", [
    {"mid": "456"}, {"pn": "2"}, {"ps": "50"}, {"order": "click"},
])
def test_catalog_cache_preserves_each_page_dimension(monkeypatch, changed):
    url = "https://api.bilibili.com/x/space/wbi/arc/search"
    params = {"mid": "123", "pn": "1", "ps": "30", "order": "pubdate", "wts": "100", "w_rid": "old"}
    upstream = Mock(return_value=response())
    monkeypatch.setattr(cache, "guarded_get", upstream)
    cache.cached_get(url, params=params)
    cache.cached_get(url, params={**params, **changed, "wts": "200", "w_rid": "new"})
    assert upstream.call_count == 2


def test_catalog_cache_keeps_cookies_isolated_when_signatures_change(monkeypatch):
    url = "https://api.bilibili.com/x/space/wbi/arc/search"
    params = {"mid": "123", "pn": "1", "wts": "100", "w_rid": "old"}
    upstream = Mock(return_value=response())
    monkeypatch.setattr(cache, "guarded_get", upstream)
    cache.cached_get(url, params=params, headers={"Cookie": "SESSDATA=first"})
    cache.cached_get(url, params={**params, "wts": "200", "w_rid": "new"}, headers={"Cookie": "SESSDATA=second"})
    assert upstream.call_count == 2


def test_only_catalog_search_ignores_wbi_signature_parameters(monkeypatch):
    upstream = Mock(return_value=response())
    monkeypatch.setattr(cache, "guarded_get", upstream)
    for url in (URL, "https://other.example/x/space/wbi/arc/search"):
        cache.cached_get(url, params={"wts": "100", "w_rid": "old"})
        cache.cached_get(url, params={"wts": "200", "w_rid": "new"})
    assert upstream.call_count == 4


def test_cached_result_remains_usable_during_cooldown_but_expiry_uses_guard(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(cache.time, "monotonic", lambda: now[0])
    upstream = Mock(return_value=response())
    monkeypatch.setattr(guard.httpx, "get", upstream)
    assert cache.cached_get(URL, ttl=120).status_code == 200
    guard.trip("字幕接口受限", "subtitle")
    now[0] += 119
    assert cache.cached_get(URL, ttl=120).status_code == 200
    now[0] += 1
    with pytest.raises(guard.BilibiliAccessBlocked):
        cache.cached_get(URL, ttl=120)
    upstream.assert_called_once()


@pytest.mark.parametrize("bad_response", [
    response(status=500), response(status=302), response(content=b"not JSON"),
    response({"code": -352}), response({"code": -101}),
    response({"code": -352, "body": []}), response({"code": "0"}),
    response({"code": False}), response({"body": "invalid"}), response([1, 2, 3]),
])
def test_error_or_invalid_responses_are_never_cached(monkeypatch, bad_response):
    upstream = Mock(return_value=bad_response)
    monkeypatch.setattr(cache, "guarded_get", upstream)
    assert cache.cached_get(URL) is bad_response
    assert cache.cached_get(URL) is bad_response
    assert upstream.call_count == 2
    assert not cache._entries


@pytest.mark.parametrize("error", [
    httpx.ConnectError("network unavailable"), guard.BilibiliAccessBlocked("风控"),
])
def test_exceptions_are_not_cached(monkeypatch, error):
    upstream = Mock(side_effect=[error, response()])
    monkeypatch.setattr(cache, "guarded_get", upstream)
    with pytest.raises(type(error)):
        cache.cached_get(URL)
    assert cache.cached_get(URL).status_code == 200
    assert cache.cached_get(URL).status_code == 200
    assert upstream.call_count == 2


def test_capacity_is_bounded_and_recently_read_entries_survive(monkeypatch):
    upstream = Mock(return_value=response())
    monkeypatch.setattr(cache, "guarded_get", upstream)
    for number in range(128):
        cache.cached_get(URL, params={"cid": number})
    cache.cached_get(URL, params={"cid": 0})
    cache.cached_get(URL, params={"cid": 128})
    assert len(cache._entries) == 128
    assert upstream.call_count == 129
    cache.cached_get(URL, params={"cid": 0})
    assert upstream.call_count == 129
    cache.cached_get(URL, params={"cid": 1})
    assert upstream.call_count == 130
    assert len(cache._entries) == 128


def test_disabled_ttl_always_uses_guard(monkeypatch):
    upstream = Mock(return_value=response())
    monkeypatch.setattr(cache, "guarded_get", upstream)
    cache.cached_get(URL)
    cache.cached_get(URL, ttl=0)
    cache.cached_get(URL, ttl=-1)
    assert upstream.call_count == 3


def test_concurrent_cache_writes_stay_bounded(monkeypatch):
    upstream = Mock(side_effect=lambda *args, **kwargs: response())
    monkeypatch.setattr(cache, "guarded_get", upstream)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda i: cache.cached_get(URL, params={"cid": i}), range(160)))
    assert all(item.status_code == 200 for item in results)
    assert len(cache._entries) == 128


def test_clear_does_not_allow_inflight_request_to_repopulate_old_cache(monkeypatch):
    entered = threading.Event()
    finish = threading.Event()

    def upstream(*args, **kwargs):
        entered.set()
        assert finish.wait(5)
        return response()

    monkeypatch.setattr(cache, "guarded_get", upstream)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(cache.cached_get, URL)
        try:
            assert entered.wait(5)
            cache.clear()
        finally:
            finish.set()
        assert pending.result(timeout=5).status_code == 200
    assert not cache._entries
