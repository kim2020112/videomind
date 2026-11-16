"""Bounded anonymous thumbnail cache; only validated fetch results are stored."""
from collections import OrderedDict
from concurrent.futures import Future
import threading
import time

_lock = threading.Lock()
_entries = OrderedDict()
_inflight = {}
TTL = 3600
MAX_BYTES = 32 * 1024 * 1024
MAX_ENTRIES = 256


def cached_thumbnail(url, fetch):
    with _lock:
        now = time.monotonic()
        for key in [key for key, (until, _) in _entries.items() if until <= now]:
            del _entries[key]
        if url in _entries:
            _entries.move_to_end(url)
            return _entries[url][1]
        future = _inflight.get(url)
        leader = future is None
        if leader:
            future = _inflight[url] = Future()
    if not leader:
        return future.result(timeout=90)
    try:
        result = fetch()
        with _lock:
            if len(result.content) <= MAX_BYTES:
                _entries[url] = (time.monotonic() + TTL, result)
                while len(_entries) > MAX_ENTRIES or sum(len(item[1].content) for item in _entries.values()) > MAX_BYTES:
                    _entries.popitem(last=False)
        future.set_result(result)
        return result
    except BaseException as exc:
        future.set_exception(exc)
        raise
    finally:
        with _lock:
            _inflight.pop(url, None)
