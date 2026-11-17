"""Regression for slow headers/body, queue isolation and cross-process slots."""
import asyncio
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api import media_security, routes
from core import bilibili_guard as guard, thumbnail_cache as cache


def test_ten_one_second_images_finish_under_four_seconds(monkeypatch):
    # Exercise the actual guard, body reader and dedicated executor, no external network.
    monkeypatch.setitem(guard.LIMITS, 'thumbnail', (0.25, ((60, 120), (3600, 1200), (86400, 3000))))
    lock = threading.Lock()
    active = peak = 0

    class Image:
        status = 200
        def __init__(self):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            self.done = False
        def getheader(self, key, default=None):
            return 'image/jpeg' if key == 'Content-Type' else default
        def read(self, amount):
            if self.done:
                return b''
            time.sleep(1)
            self.done = True
            return b'image'
        def close(self):
            nonlocal active
            with lock:
                active -= 1

    def resolver(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port))]

    async def scenario():
        started = time.monotonic()
        jobs = [cache.load_thumbnail(f'https://i0.hdslb.com/bfs/archive/{i}.jpg',
                 lambda: media_security.fetch_thumbnail('https://i0.hdslb.com/bfs/archive/x.jpg',
                          resolver=resolver, opener=lambda *_: Image()), {}) for i in range(10)]
        results = await asyncio.gather(*jobs)
        elapsed = time.monotonic() - started
        assert len(results) == 10
        assert 2 <= peak <= 4
        assert elapsed < 4, elapsed
        print(f'10 images, 1s body each: {elapsed:.3f}s, peak={peak}')
    asyncio.run(scenario())


def test_slow_thumbnail_does_not_hold_api_lock():
    entered = threading.Event()
    release = threading.Event()
    def slow():
        with guard.thumbnail_download_slot(), guard.request_slot('thumbnail', 'thumbnail'):
            entered.set()
            assert release.wait(3)
    with ThreadPoolExecutor(max_workers=2) as pool:
        job = pool.submit(slow)
        assert entered.wait(2)
        try:
            started = time.monotonic()
            with guard.request_slot('api', 'metadata'):
                assert time.monotonic() - started < 0.5
        finally:
            release.set()
        job.result(timeout=3)


def test_thumbnail_quota_and_cooldown_do_not_block_api(monkeypatch):
    monkeypatch.setitem(guard.LIMITS, 'thumbnail', (0, ((60, 1),)))
    with guard.request_slot('thumbnail', 'thumbnail'):
        pass
    with pytest.raises(guard.BilibiliAccessBlocked):
        with guard.request_slot('thumbnail', 'thumbnail'):
            pytest.fail('quota bypass')
    with guard.request_slot('api', 'metadata'):
        pass
    with pytest.raises(guard.BilibiliAccessBlocked):
        guard.check_response(429, kind='thumbnail', scope='thumbnail', retry_after='300')
    guard.assert_allowed('metadata')
    with pytest.raises(guard.BilibiliAccessBlocked):
        guard.assert_allowed('thumbnail')
    guard.trip('global', 'all')
    with pytest.raises(guard.BilibiliAccessBlocked):
        with guard.request_slot('thumbnail', 'thumbnail'):
            pytest.fail('global cooldown bypass')


def test_thumbnail_route_etag_and_conditional_response(monkeypatch):
    calls = []
    def fetch(*args, **kwargs):
        calls.append(1)
        return SimpleNamespace(content=b'image', content_type='image/jpeg')
    monkeypatch.setattr(routes, 'fetch_thumbnail', fetch)
    async def scenario():
        url = 'https://i0.hdslb.com/bfs/archive/etag.jpg'
        first = await routes.proxy_thumbnail(url)
        request = Request({'type': 'http', 'headers': [(b'if-none-match', first.headers['etag'].encode())]})
        second = await routes.proxy_thumbnail(url, request)
        assert second.status_code == 304
        assert second.body == b''
        assert len(calls) == 1
    asyncio.run(scenario())


def test_download_slots_are_shared_across_processes():
    import os
    import subprocess
    import sys
    from contextlib import ExitStack

    # A fresh interpreter has no inherited Python semaphore: only the file slots
    # can keep it out while four complete downloads are active in this process.
    script = '''from core.bilibili_guard import thumbnail_download_slot
print('ready', flush=True)
with thumbnail_download_slot():
    print('admitted', flush=True)
'''
    with ExitStack() as stack:
        for _ in range(4):
            stack.enter_context(guard.thumbnail_download_slot())
        env = {**os.environ, 'BILIBILI_GUARD_PATH': str(guard.STATE_PATH)}
        child = subprocess.Popen([sys.executable, '-c', script], env=env, stdout=subprocess.PIPE, text=True)
        try:
            assert child.stdout.readline().strip() == 'ready'
            time.sleep(0.15)
            assert child.poll() is None
            # Releasing a single slot must let the child proceed.
            stack.pop_all().close()
            output, _ = child.communicate(timeout=3)
            assert 'admitted' in output
            assert child.returncode == 0
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
