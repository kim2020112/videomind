"""Small in-memory cache for successful Bilibili JSON responses.

Expired and missing entries always go through the shared access guard. Keys are
credential-sensitive digests; neither credentials nor cache data are persisted.
"""

from __future__ import annotations

from concurrent.futures import Future
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

import httpx

from core.bilibili_guard import guarded_get

MAX_ENTRIES = 128


@dataclass(frozen=True)
class _Entry:
    expires_at: float
    content: bytes


_entries: OrderedDict[str, _Entry] = OrderedDict()
_lock = threading.Lock()
_generation = 0
_inflight = {}
_latest_write = {}
_refresh = ContextVar("bilibili_refresh", default=False)


def clear() -> None:
    """Forget cached responses, including writes from requests already running."""
    global _generation
    with _lock:
        _entries.clear()
        _generation += 1


def _request_key(url: str, kwargs: dict):
    # Auth objects may produce credentials dynamically. A conservative cache
    # miss is preferable to sharing results across unidentifiable identities.
    if kwargs.get("auth") is not None:
        return None, None
    try:
        request = httpx.Request(
            "GET", url, params=kwargs.get("params"),
            headers=kwargs.get("headers"), cookies=kwargs.get("cookies"),
        )
        key_url = request.url
        if key_url.host == "api.bilibili.com" and key_url.path in ("/x/space/wbi/arc/search", "/x/player/wbi/v2"):
            # A new WBI timestamp/signature does not change a catalog page.
            # Normalize only the cache identity; the outbound request retains
            # its original signed parameters and all page/account dimensions.
            query = httpx.QueryParams([
                (name, value) for name, value in key_url.params.multi_items()
                if name not in ("wts", "w_rid")
            ])
            key_url = key_url.copy_with(query=str(query).encode())
        identity = [
            str(key_url),
            sorted((name.decode("latin1").lower(), value.decode("latin1")) for name, value in request.headers.raw),
        ]
        digest = hashlib.sha256(json.dumps(identity, ensure_ascii=True).encode()).hexdigest()
        return digest, request
    except (TypeError, ValueError):
        return None, None


def _cacheable(payload) -> bool:
    if not isinstance(payload, dict):
        return False
    if "code" in payload:
        data = payload.get('data')
        subtitle = data.get('subtitle') if isinstance(data, dict) else None
        if isinstance(subtitle, dict):
            tracks = subtitle.get('subtitles') or []
            # Login-hidden and placeholder metadata must not trap manual retry
            # behind a two-minute "successful" response cache.
            if data.get('need_login_subtitle') or not any(
                isinstance(track, dict) and track.get('subtitle_url') for track in tracks
            ):
                return False
        return type(payload["code"]) is int and payload["code"] == 0
    return isinstance(payload.get("body"), list)


def _cached_get(url: str, *, ttl: float = 120, _write_token=None, **kwargs):
    """Return a recent successful JSON response, or make one protected request."""
    if ttl <= 0:
        return guarded_get(url, **kwargs)
    key, request = _request_key(url, kwargs)
    if key is None:
        return guarded_get(url, **kwargs)

    with _lock:
        now = time.monotonic()
        entry = _entries.get(key)
        if not _refresh.get() and entry is not None and entry.expires_at > now:
            _entries.move_to_end(key)
            return httpx.Response(
                200, content=entry.content, headers={"Content-Type": "application/json; charset=utf-8"},
                request=request,
            )
        _entries.pop(key, None)
        generation = _generation

    response = guarded_get(url, **kwargs)
    if response.status_code != 200:
        return response
    try:
        payload = response.json()
        nav_material = (request.url.host == 'api.bilibili.com' and request.url.path == '/x/web-interface/nav'
                        and isinstance(payload, dict) and payload.get('code') == -101
                        and isinstance(payload.get('data'), dict) and bool(payload['data'].get('wbi_img')))
        if not _cacheable(payload) and not nav_material:
            return response
        if request.url.path in ('/x/player/v2', '/x/player/wbi/v2'):
            data = payload.get('data') or {}
            params = request.url.params
            if any(data.get(k) and str(data[k]) != params.get(k) for k in ('bvid', 'cid') if params.get(k)):
                return response
            from core.subtitle_identity import subtitle_link_identity, SubtitleIdentityError
            for track in (data.get('subtitle') or {}).get('subtitles') or []:
                if not isinstance(track, dict):
                    return response
                link = track.get('subtitle_url') or ''
                if link:
                    link = 'https:' + link if link.startswith('//') else link.replace('http://', 'https://', 1)
                    try:
                        subtitle_link_identity(link, data.get('aid'), data.get('cid'))
                    except SubtitleIdentityError:
                        return response
        content = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    except (TypeError, ValueError, UnicodeError, AttributeError):
        return response

    with _lock:
        if generation != _generation or (_write_token is not None and _latest_write.get(key) is not _write_token):
            return response
        now = time.monotonic()
        for expired in [item for item, value in _entries.items() if value.expires_at <= now]:
            del _entries[expired]
        _entries[key] = _Entry(expires_at=now + ttl, content=content)
        _entries.move_to_end(key)
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)
    return response


@contextmanager
def refresh_responses(enabled=True):
    token = _refresh.set(enabled)
    try:
        yield
    finally:
        _refresh.reset(token)


def cached_get(url: str, *, ttl: float = 120, **kwargs):
    key, _ = _request_key(url, kwargs)
    if key is None or ttl <= 0:
        return _cached_get(url, ttl=ttl, **kwargs)
    # Explicit refresh never joins a request started before that refresh.
    with _lock:
        refresh = _refresh.get()
        entry = _entries.get(key)
        if not refresh and entry is not None and entry.expires_at > time.monotonic():
            _entries.move_to_end(key)
            _, request = _request_key(url, kwargs)
            return httpx.Response(200, content=entry.content,
                                  headers={'Content-Type': 'application/json; charset=utf-8'}, request=request)
        flight_key = (key, _generation, refresh)
        future = _inflight.get((key, _generation, True)) if not refresh else None
        future = future or _inflight.get(flight_key)
        leader = future is None
        if leader:
            future = _inflight[flight_key] = Future()
            _latest_write[key] = future
    if not leader:
        result = future.result(timeout=90)
        # Response close/stream state belongs to each caller.
        return httpx.Response(result.status_code, content=result.content, headers=result.headers, request=result.request)
    try:
        result = _cached_get(url, ttl=ttl, _write_token=future, **kwargs)
        future.set_result(result)
        return result
    except BaseException as exc:
        future.set_exception(exc)
        raise
    finally:
        with _lock:
            _inflight.pop(flight_key, None)
            if _latest_write.get(key) is future:
                _latest_write.pop(key, None)
