"""Shared, persistent limits for Bilibili access, including worker processes.

No credentials are stored here. API and media calls are serialized separately;
thumbnail admission is independent of network I/O, with four download slots.
SQLite retains budgets and the circuit breaker across restarts.
"""

from __future__ import annotations

import math
import fcntl
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from config import BASE_DIR

STATE_PATH = Path(os.getenv("BILIBILI_GUARD_PATH", str(BASE_DIR / "db" / "bilibili_guard.db")))
COOLDOWN_SECONDS = 10 * 60
MAX_COOLDOWN_SECONDS = 60 * 60
# Application limits, not a claim about the platform's safe request threshold.
LIMITS = {"api": (5.0, ((3600, 120), (86400, 600))),
          "media": (0.25, ((60, 120), (3600, 1200), (86400, 3000))),
          "thumbnail": (0.25, ((60, 120), (3600, 1200), (86400, 3000)))}
RISK_CODES = frozenset((-111, -352, -401, -412, -509, -799))
SCOPE_NAMES = {"all": "请求", "catalog": "投稿列表", "subtitle": "字幕", "video": "视频解析", "metadata": "视频信息", "media": "媒体资源", "account": "登录验证", "thumbnail": "封面图片"}
_LOCK = threading.Lock()
_MEDIA_LOCK = threading.Lock()
_THUMBNAIL_ADMISSION_LOCK = threading.Lock()
_THUMBNAIL_SLOTS = threading.BoundedSemaphore(4)
logger = logging.getLogger(__name__)


class BilibiliAccessBlocked(RuntimeError):
    def __init__(self, message: str, code: str = "protection"):
        super().__init__(message)
        self.code = code


def is_bilibili_url(url: str, include_cdn: bool = True) -> bool:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    domains = ("bilibili.com", "b23.tv")
    if include_cdn:
        domains += ("hdslb.com", "biliimg.com", "bilivideo.com", "bilivideo.cn", "bilivideo.net")
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def request_kind(url: str) -> str:
    return "api" if is_bilibili_url(url, include_cdn=False) else "media"


def request_scope(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path
    host = (parsed.hostname or '').lower()
    if (host == 'hdslb.com' or host.endswith('.hdslb.com') or host == 'biliimg.com' or host.endswith('.biliimg.com')) and path.startswith(('/bfs/archive/', '/bfs/face/')):
        return 'thumbnail'
    if path == '/x/web-interface/nav':
        return 'account'
    if path.startswith('/x/space/') or path == '/x/web-interface/card':
        return 'catalog'
    if path in ('/x/player/v2', '/x/player/wbi/v2', '/x/v2/dm/view') or 'subtitle' in (parsed.hostname or '') or path.endswith('.json'):
        return 'subtitle'
    if parsed.hostname == 'api.bilibili.com':
        return 'metadata'
    return 'video' if request_kind(url) == 'api' else 'media'


@contextmanager
def _database():
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(STATE_PATH, timeout=5)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS protection (id INTEGER PRIMARY KEY CHECK(id=1), blocked_until REAL NOT NULL, reason TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS cooldowns (scope TEXT PRIMARY KEY, blocked_until REAL NOT NULL, reason TEXT NOT NULL, strikes INTEGER NOT NULL, last_trigger REAL NOT NULL)")
        # One-time migration of the original 24-hour policy. Keep the original
        # event time; opening the database must never start a fresh cooldown.
        old = connection.execute("SELECT blocked_until, reason FROM protection WHERE id=1").fetchone()
        if old:
            trigger = old[0] - 86400
            # A manually imposed historical pause is not a new platform refusal.
            until = 0 if old[1].startswith('近期目录同步') else trigger + COOLDOWN_SECONDS
            connection.execute("INSERT OR IGNORE INTO cooldowns VALUES ('all', ?, ?, 1, ?)", (until, old[1], trigger))
            connection.execute("DELETE FROM protection WHERE id=1")
        connection.execute("CREATE TABLE IF NOT EXISTS requests (at REAL NOT NULL, kind TEXT NOT NULL)")
        connection.execute("CREATE INDEX IF NOT EXISTS request_time ON requests(kind, at)")
        connection.commit()
        yield connection
        connection.commit()
    finally:
        connection.close()


def _check(connection, now: float, scope: str) -> None:
    row = connection.execute(
        "SELECT blocked_until, reason, scope FROM cooldowns WHERE scope IN ('all', ?) AND blocked_until>? ORDER BY blocked_until DESC LIMIT 1",
        (scope, now),
    ).fetchone()
    if row:
        remaining = max(1, int((row[0] - now + 59) // 60))
        label = SCOPE_NAMES.get(row[2], '请求')
        raise BilibiliAccessBlocked(
            f"B 站{label}暂时受限，约 {remaining} 分钟后可重试：{row[1]}。已有缓存可继续使用", 'rate_limit')


def assert_allowed(scope: str = 'all') -> None:
    try:
        with _database() as connection:
            _check(connection, time.time(), scope)
    except (OSError, sqlite3.Error) as exc:
        raise BilibiliAccessBlocked("B 站访问保护状态不可用，已停止联网") from exc


def trip(reason: str, scope: str = 'all', *, retry_after: float = 0) -> None:
    """Back off only the refused feature: 10, 20, 40, then at most 60 minutes."""
    try:
        with _database() as connection:
            connection.execute('BEGIN IMMEDIATE')
            now = time.time()
            row = connection.execute('SELECT strikes, last_trigger FROM cooldowns WHERE scope=?', (scope,)).fetchone()
            strikes = min(row[0] + 1, 4) if row and now - row[1] < 86400 else 1
            base, maximum = (120, 600) if scope == 'thumbnail' else (COOLDOWN_SECONDS, MAX_COOLDOWN_SECONDS)
            delay = max(min(maximum, base * (2 ** (strikes - 1))), retry_after)
            connection.execute(
                'INSERT INTO cooldowns VALUES (?, ?, ?, ?, ?) ON CONFLICT(scope) DO UPDATE SET blocked_until=excluded.blocked_until, reason=excluded.reason, strikes=excluded.strikes, last_trigger=excluded.last_trigger',
                (scope, now + delay, reason, strikes, now),
            )
    except (OSError, sqlite3.Error) as exc:
        raise BilibiliAccessBlocked("无法保存 B 站保护状态，已停止联网") from exc


def check_response(status: int, payload=None, *, kind: str = 'api', scope: str = 'all', retry_after: str | None = None) -> None:
    code = payload.get('code') if isinstance(payload, dict) else None
    if status in (412, 429) or (status == 403 and kind == 'api') or code in RISK_CODES:
        # Account API 429 pauses all access. Anonymous CDN refusal stays local.
        affected = 'all' if status == 429 and kind == 'api' else scope
        reason = f"接口限制请求（HTTP {status}" + (f"，code={code}" if code is not None else '') + '）'
        delay = 0
        if status == 429 and retry_after:
            try:
                delay = max(0, float(retry_after))
            except (ValueError, TypeError):
                try:
                    from email.utils import parsedate_to_datetime
                    delay = max(0, parsedate_to_datetime(retry_after).timestamp() - time.time())
                except (ValueError, TypeError, OverflowError):
                    pass
        if not math.isfinite(delay):
            delay = 0
        trip(reason, affected, retry_after=delay)
        assert_allowed(affected)
    if status == 403 and kind in ('media', 'thumbnail'):
        raise BilibiliAccessBlocked('B 站媒体链接拒绝访问或已过期，请重新打开视频刷新链接')


@contextmanager
def request_slot(kind: str = "api", scope: str = "all"):
    """One admitted request, no automatic retry. Recheck after waiting."""
    if kind not in LIMITS and not (kind == "thumbnail" and "media" in LIMITS):
        raise ValueError(f"unknown request kind: {kind}")
    thumbnail_slot = kind == "thumbnail"
    lock = _THUMBNAIL_ADMISSION_LOCK if thumbnail_slot else _MEDIA_LOCK if kind == "media" else _LOCK
    suffix = ".thumbnail.lock" if thumbnail_slot else ".media.lock" if kind == "media" else ".lock"
    started = time.monotonic()
    lock_wait = rate_wait = 0.0
    admitted_at = None
    outcome = "stopped"
    if not lock.acquire(timeout=30):
        raise BilibiliAccessBlocked("B 站请求正在排队，请稍后手动继续", "budget")
    lockfile = None
    acquired = False
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        lockfile = open(str(STATE_PATH) + suffix, "a")
        deadline = time.monotonic() + 30
        while not acquired:
            try:
                fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise BilibiliAccessBlocked("B 站请求正在排队，请稍后手动继续", "budget")
                time.sleep(0.1)
        lock_wait = time.monotonic() - started
        interval, budgets = LIMITS[kind] if kind in LIMITS else LIMITS["media"]
        with _database() as connection:
            now = time.time()
            _check(connection, now, scope)
            latest = connection.execute("SELECT max(at) FROM requests WHERE kind=?", (kind,)).fetchone()[0]
            wait = max(0, (latest or 0) + interval - now)
        if wait:
            waiting_at = time.monotonic()
            time.sleep(wait)
            rate_wait = time.monotonic() - waiting_at
        with _database() as connection:
            # Separate kinds may be admitted concurrently. Keep protection,
            # budget checks and accounting atomic with other admissions/trips.
            # This short transaction never spans rate waiting or network I/O.
            connection.execute("BEGIN IMMEDIATE")
            now = time.time()
            _check(connection, now, scope)
            for period, maximum in budgets:
                count = connection.execute("SELECT count(*) FROM requests WHERE kind=? AND at>?", (kind, now-period)).fetchone()[0]
                if count >= maximum:
                    raise BilibiliAccessBlocked("已达到 B 站本地请求额度，任务已暂停；请稍后手动继续或使用已有缓存", "budget")
            connection.execute("DELETE FROM requests WHERE at<=?", (now-86400,))
            connection.execute("INSERT INTO requests VALUES (?, ?)", (now, kind))
        # Thumbnail downloads are admitted and counted before the network call,
        # but do not hold the admission lock while reading a slow image.
        # API and media each retain serialization within their own kind, so an
        # API's five-second wait cannot hold up an already-known subtitle URL.
        if thumbnail_slot:
            if lockfile is not None and acquired:
                fcntl.flock(lockfile, fcntl.LOCK_UN)
                acquired = False
            lockfile.close()
            lockfile = None
            lock.release()
            lock = None
        admitted_at = time.monotonic()
        yield
        outcome = "completed"
    except (OSError, sqlite3.Error) as exc:
        # HTTP libraries' transport errors are handled by their callers. Local
        # state/locking errors must not fail open.
        raise BilibiliAccessBlocked("B 站访问保护或连接不可用，已停止本次联网") from exc
    finally:
        if lockfile is not None:
            if acquired:
                fcntl.flock(lockfile, fcntl.LOCK_UN)
            lockfile.close()
        if lock is not None:
            lock.release()
        if not thumbnail_slot:
            logger.info(
                "bilibili_request kind=%s scope=%s lock_wait_ms=%.1f rate_wait_ms=%.1f active_ms=%.1f outcome=%s",
                kind, scope, lock_wait * 1000, rate_wait * 1000,
                (time.monotonic() - admitted_at) * 1000 if admitted_at is not None else 0,
                outcome,
            )


@contextmanager
def thumbnail_download_slot():
    """Bound complete image downloads to four, across threads and processes."""
    if not _THUMBNAIL_SLOTS.acquire(timeout=30):
        raise BilibiliAccessBlocked("封面请求正在排队，请稍后重试", "budget")
    slot = None
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + 30
        while slot is None:
            for index in range(4):
                candidate = open(str(STATE_PATH) + f".thumbnail-{index}.lock", "a")
                try:
                    fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    slot = candidate
                    break
                except BlockingIOError:
                    candidate.close()
                except BaseException:
                    candidate.close()
                    raise
            if slot is None:
                if time.monotonic() >= deadline:
                    raise BilibiliAccessBlocked("封面请求正在排队，请稍后重试", "budget")
                time.sleep(0.05)
        yield
    except (OSError, sqlite3.Error) as exc:
        raise BilibiliAccessBlocked("封面访问保护不可用，已停止本次联网") from exc
    finally:
        if slot is not None:
            fcntl.flock(slot, fcntl.LOCK_UN)
            slot.close()
        _THUMBNAIL_SLOTS.release()


def guarded_get(url: str, **kwargs):
    """Read-only HTTP request, including JSON risk codes before releasing slot.

    Redirects are returned to callers; no credential can follow a redirect.
    Subtitle CDN URLs never receive account credentials.
    """
    headers = dict(kwargs.pop("headers", {}) or {})
    host = (urlsplit(url).hostname or "").lower()
    if urlsplit(url).scheme != 'https' or not (host == "bilibili.com" or host.endswith(".bilibili.com")):
        headers = {k: v for k, v in headers.items() if k.lower() not in ("cookie", "authorization")}
    kwargs.pop("follow_redirects", None)
    kind = request_kind(url)
    scope = request_scope(url)
    with request_slot(kind, scope):
        response = httpx.get(url, headers=headers, follow_redirects=False, **kwargs)
        try:
            check_response(response.status_code, kind=kind, scope=scope, retry_after=response.headers.get("Retry-After"))
            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                check_response(response.status_code, payload, kind=kind, scope=scope)
            return response
        except BaseException:
            response.close()
            raise
