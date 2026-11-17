from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from core import thumbnail_cache as cache


def test_cache_reuses_images_and_failure_is_not_saved():
    cache._entries.clear()
    fetch = Mock(return_value=SimpleNamespace(content=b'image', content_type='image/jpeg'))
    assert cache.cached_thumbnail('https://test/image', fetch).content == b'image'
    assert cache.cached_thumbnail('https://test/image', fetch).content == b'image'
    assert fetch.call_count == 1
    failure = Mock(side_effect=ValueError('blocked'))
    for _ in range(2):
        with pytest.raises(ValueError):
            cache.cached_thumbnail('https://test/fail', failure)
    assert failure.call_count == 2


def test_disk_survives_memory_reset_and_evicts_expired_entries(monkeypatch):
    fetch = Mock(return_value=SimpleNamespace(content=b'image', content_type='image/jpeg'))
    cache.cached_thumbnail('disk', fetch)
    cache._entries.clear()
    metrics = {}
    assert cache.cached_thumbnail('disk', fetch, metrics).content == b'image'
    assert metrics['cache'] == 'disk'
    assert fetch.call_count == 1
    cache._entries.clear()
    with cache.closing(cache._disk_connection()) as connection, connection:
        connection.execute('UPDATE images SET expires=0')
    cache.cached_thumbnail('disk', fetch)
    assert fetch.call_count == 2


def test_disk_budget_and_failure_fallback(monkeypatch):
    monkeypatch.setattr(cache, 'DISK_MAX_BYTES', 5)
    fetch = Mock(return_value=SimpleNamespace(content=b'1234', content_type='image/jpeg'))
    cache.cached_thumbnail('one', fetch)
    cache.cached_thumbnail('two', fetch)
    cache._entries.clear()
    assert cache.lookup_thumbnail('one') is None
    assert cache.lookup_thumbnail('two').content == b'1234'
    monkeypatch.setattr(cache, 'DISK_PATH', cache.DISK_PATH.parent)  # directory: unavailable cache
    assert cache.cached_thumbnail('fallback', fetch).content == b'1234'


def test_concurrent_duplicates_download_once():
    import threading
    from concurrent.futures import ThreadPoolExecutor
    entered = threading.Event()
    release = threading.Event()

    def download():
        entered.set()
        assert release.wait(3)
        return SimpleNamespace(content=b'image', content_type='image/jpeg')

    fetch = Mock(side_effect=download)
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = [pool.submit(cache.cached_thumbnail, 'shared', fetch) for _ in range(8)]
        assert entered.wait(3)
        release.set()
        assert all(job.result(timeout=3).content == b'image' for job in jobs)
    assert fetch.call_count == 1


def test_executor_is_bounded_and_cache_hits_bypass_queue():
    import asyncio
    import threading
    from fastapi import HTTPException

    async def scenario():
        cache._remember('warm', SimpleNamespace(content=b'warm', content_type='image/jpeg'))
        original = cache._pending
        cache._pending = threading.BoundedSemaphore(0)
        try:
            assert (await cache.load_thumbnail('warm', Mock(), {})).content == b'warm'
            with pytest.raises(HTTPException) as raised:
                await cache.load_thumbnail('cold', Mock(), {})
            assert raised.value.status_code == 503
            assert raised.value.headers['Retry-After'] == '2'
        finally:
            cache._pending = original
    asyncio.run(scenario())


def test_async_duplicate_survives_one_client_cancel():
    import asyncio
    import threading

    async def scenario():
        entered, release = threading.Event(), threading.Event()
        calls = []
        def download():
            calls.append(1)
            entered.set()
            assert release.wait(3)
            return SimpleNamespace(content=b'image', content_type='image/jpeg')
        first = asyncio.create_task(cache.load_thumbnail('cancel', download, {}))
        while not entered.is_set():
            await asyncio.sleep(0.01)
        second = asyncio.create_task(cache.load_thumbnail('cancel', download, {}))
        await asyncio.sleep(0.05)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        assert (await asyncio.wait_for(second, 3)).content == b'image'
        assert len(calls) == 1
    asyncio.run(scenario())


def test_disk_expiry_is_not_extended_by_memory_promotion(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(cache.time, 'time', lambda: now[0])
    monkeypatch.setattr(cache.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(cache, 'DISK_TTL', 10)
    fetch = Mock(return_value=SimpleNamespace(content=b'image', content_type='image/jpeg'))
    cache.cached_thumbnail('expiry', fetch)
    cache._entries.clear()
    now[0] = 1009
    assert cache.lookup_thumbnail('expiry').content == b'image'
    now[0] = 1011
    assert cache.lookup_thumbnail('expiry') is None


def test_memory_hit_never_waits_for_default_executor(monkeypatch):
    import asyncio
    cache._remember('memory', SimpleNamespace(content=b'image', content_type='image/jpeg'))
    monkeypatch.setattr(asyncio, 'to_thread', Mock(side_effect=AssertionError('executor should not be used')))
    async def scenario():
        metrics = {}
        assert (await cache.load_thumbnail('memory', Mock(), metrics)).content == b'image'
        assert metrics['cache'] == 'memory'
    asyncio.run(scenario())
