"""Bounded anonymous image cache and an isolated, bounded download executor."""
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
import asyncio
import hashlib
import logging
import os
import sqlite3
import threading
import time

from config import BASE_DIR

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_entries = OrderedDict()
_inflight = {}
TTL = 3600
MAX_BYTES = 32 * 1024 * 1024
MAX_ENTRIES = 256
DISK_PATH = Path(os.getenv('THUMBNAIL_CACHE_PATH', str(BASE_DIR / 'db' / 'thumbnails.db')))
DISK_TTL = 7 * 86400
DISK_MAX_BYTES = 256 * 1024 * 1024
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='thumbnail')
_pending = threading.BoundedSemaphore(20)  # four active, sixteen waiting
_async_inflight = {}


def _disk_connection():
    DISK_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DISK_PATH, timeout=2)
    try:
        connection.execute('CREATE TABLE IF NOT EXISTS images (key TEXT PRIMARY KEY, content BLOB NOT NULL, content_type TEXT NOT NULL, expires REAL NOT NULL, accessed REAL NOT NULL)')
        connection.execute('CREATE INDEX IF NOT EXISTS images_accessed ON images(accessed)')
        return connection
    except BaseException:
        connection.close()
        raise


def _disk_read(url):
    try:
        now = time.time()
        with closing(_disk_connection()) as connection, connection:
            row = connection.execute('SELECT content, content_type, expires FROM images WHERE key=?', (url,)).fetchone()
            if row and row[2] > now:
                connection.execute('UPDATE images SET accessed=? WHERE key=?', (now, url))
                return SimpleNamespace(content=bytes(row[0]), content_type=row[1], cache_expires=row[2])
            if row:
                connection.execute('DELETE FROM images WHERE key=?', (url,))
    except (OSError, sqlite3.Error):
        logger.warning('Thumbnail disk cache read failed', exc_info=True)
    return None


def _disk_write(url, payload):
    if len(payload.content) > DISK_MAX_BYTES:
        return
    try:
        now = time.time()
        with closing(_disk_connection()) as connection, connection:
            connection.execute('DELETE FROM images WHERE expires<=?', (now,))
            connection.execute('INSERT OR REPLACE INTO images VALUES (?, ?, ?, ?, ?)',
                               (url, payload.content, payload.content_type, now + DISK_TTL, now))
            size = connection.execute('SELECT COALESCE(SUM(length(content)), 0) FROM images').fetchone()[0]
            for key, count in connection.execute('SELECT key, length(content) FROM images ORDER BY accessed').fetchall():
                if size <= DISK_MAX_BYTES:
                    break
                connection.execute('DELETE FROM images WHERE key=?', (key,))
                size -= count
            # Reuse deleted pages rather than growing a new file on each eviction.
    except (OSError, sqlite3.Error):
        logger.warning('Thumbnail disk cache write failed', exc_info=True)


def _remember(url, result):
    with _lock:
        if len(result.content) <= MAX_BYTES:
            remaining = min(TTL, max(0, getattr(result, 'cache_expires', time.time() + TTL) - time.time()))
            _entries[url] = (time.monotonic() + remaining, result)
            _entries.move_to_end(url)
            while len(_entries) > MAX_ENTRIES or sum(len(item[1].content) for item in _entries.values()) > MAX_BYTES:
                _entries.popitem(last=False)


def _memory_lookup(url, metrics=None):
    with _lock:
        now = time.monotonic()
        for key in [key for key, (until, _) in _entries.items() if until <= now]:
            del _entries[key]
        if url in _entries:
            _entries.move_to_end(url)
            if metrics is not None:
                metrics['cache'] = 'memory'
            return _entries[url][1]
    return None


def lookup_thumbnail(url, metrics=None):
    result = _memory_lookup(url, metrics)
    if result is not None:
        return result
    result = _disk_read(url)
    if result is not None:
        _remember(url, result)
        if metrics is not None:
            metrics['cache'] = 'disk'
    return result


def cached_thumbnail(url, fetch, metrics=None):
    result = lookup_thumbnail(url, metrics)
    if result is not None:
        return result
    with _lock:
        # A leader may have completed between the cache lookup and this lock.
        entry = _entries.get(url)
        if entry and entry[0] > time.monotonic():
            if metrics is not None:
                metrics['cache'] = 'memory'
            return entry[1]
        future = _inflight.get(url)
        leader = future is None
        if leader:
            future = _inflight[url] = Future()
    if not leader:
        if metrics is not None:
            metrics['cache'] = 'coalesced'
        return future.result(timeout=150)
    try:
        started = time.monotonic()
        result = fetch()
        if metrics is not None:
            metrics.update(cache='miss', upstream_ms=round((time.monotonic() - started) * 1000))
        _remember(url, result)
        _disk_write(url, result)
        future.set_result(result)
        return result
    except BaseException as exc:
        future.set_exception(exc)
        raise
    finally:
        with _lock:
            _inflight.pop(url, None)


async def load_thumbnail(url, fetch, metrics):
    """Cache hits bypass the download queue; duplicate clients share one job."""
    result = _memory_lookup(url, metrics)
    if result is not None:
        return result
    result = await asyncio.to_thread(lookup_thumbnail, url, metrics)
    if result is not None:
        return result
    key = (asyncio.get_running_loop(), url)
    existing = _async_inflight.get(key)
    if existing is not None:
        metrics['cache'] = 'coalesced'
        return await asyncio.shield(existing)
    if not _pending.acquire(blocking=False):
        from fastapi import HTTPException
        raise HTTPException(503, '封面请求较多，请稍后重试', headers={'Retry-After': '2'})
    queued = time.monotonic()

    def work():
        metrics['queue_ms'] = round((time.monotonic() - queued) * 1000)
        return cached_thumbnail(url, fetch, metrics)

    try:
        job = asyncio.get_running_loop().run_in_executor(_executor, work)
    except BaseException:
        _pending.release()
        raise
    _async_inflight[key] = job

    def completed(future):
        _async_inflight.pop(key, None)
        _pending.release()
        # Consume failures even when every HTTP client has disconnected.
        if not future.cancelled():
            future.exception()

    job.add_done_callback(completed)
    return await asyncio.shield(job)


def thumbnail_id(url):
    return hashlib.sha256(url.encode()).hexdigest()[:12]
