"""Persist platform cookies; expose metadata without returning secrets."""
import fcntl
from contextlib import contextmanager
import json
import os
import tempfile
import threading
from datetime import datetime, timezone

import httpx
from config import PLATFORM_CONFIG_PATH
from core.bilibili_guard import BilibiliAccessBlocked, guarded_get

_PATH = PLATFORM_CONFIG_PATH
_LOCK = threading.RLock()
PLATFORMS = {"bilibili": "BILIBILI_COOKIE", "douyin": "DOUYIN_COOKIE"}


@contextmanager
def _edit():
    """Serialize read-modify-write across API workers as well as threads."""
    with _LOCK:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(_PATH) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def _read():
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"platforms": {}}


def _write(data):
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(dir=_PATH.parent, prefix=".platform-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(path, _PATH)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def _platform(platform):
    if platform not in PLATFORMS:
        raise ValueError("不支持的平台")


def get_cookie(platform):
    _platform(platform)
    with _LOCK:
        item = _read().get("platforms", {}).get(platform, {})
        return item.get("cookie", "") or os.getenv(PLATFORMS[platform], "").strip()


def get_public():
    with _LOCK:
        stored = _read().get("platforms", {})
        result = {}
        for name in PLATFORMS:
            item = stored.get(name, {})
            value = get_cookie(name)
            result[name] = {"configured": bool(value), "source": "saved" if item.get("cookie") else "environment" if value else "none",
                            "used_for_requests": name != "bilibili" or os.getenv("BILIBILI_USE_ACCOUNT_COOKIE", "true").lower() == "true",
                            "status": item.get("status", "untested"), "message": item.get("message", ""),
                            "last_checked_at": item.get("last_checked_at", "")}
        return {"platforms": result}


def _normalize(cookie):
    cookie = cookie.strip()
    if not cookie or len(cookie) > 32768 or any(ord(c) < 32 or ord(c) == 127 for c in cookie):
        raise ValueError("请粘贴完整的单行 Cookie（不含 Cookie: 前缀）")
    if cookie.lower().startswith("cookie:"):
        cookie = cookie[7:].strip()
    if not any(part.strip() for part in cookie.split(";")) or not all("=" in part and part.split("=", 1)[0].strip() for part in cookie.split(";") if part.strip()):
        raise ValueError("Cookie 格式应为 name=value; name2=value2")
    return cookie


def save(platform, cookie):
    _platform(platform)
    value = _normalize(cookie) if cookie.strip() else None
    with _edit():
        data = _read()
        if value is None:
            return get_public()  # Blank edits preserve the saved credential.
        data.setdefault("platforms", {})[platform] = {"cookie": value, "status": "untested"}
        _write(data)
        return get_public()


def validate(platform, cookie=""):
    _platform(platform)
    value = _normalize(cookie) if cookie.strip() else get_cookie(platform)
    if not value:
        raise ValueError("请先填写 Cookie")
    headers = {"Cookie": value, "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36"}
    status, message = "unknown", "平台返回异常，暂时无法确认登录状态，请稍后重试"
    try:
        url = "https://api.bilibili.com/x/web-interface/nav" if platform == "bilibili" else "https://www.douyin.com/aweme/v1/web/user/profile/self/?device_platform=webapp&aid=6383"
        request_get = guarded_get if platform == "bilibili" else httpx.get
        response = request_get(url, headers=headers, timeout=12, follow_redirects=False)
        if response.status_code in (403, 412, 429):
            message = "平台限制请求，暂时无法确认 Cookie 是否有效，请稍后重试"
        elif response.status_code == 200:
            payload = response.json()
            if platform == "bilibili":
                if payload.get("code") == 0 and payload.get("data", {}).get("isLogin"):
                    status, message = "valid", "B站登录有效"
                elif payload.get("code") == -101 or payload.get("data", {}).get("isLogin") is False:
                    status, message = "invalid", "B站登录已失效，请重新复制 Cookie"
            else:
                user = payload.get("user", {}) or {}
                if payload.get("status_code") == 0 and (user.get("uid") or user.get("sec_uid")):
                    status, message = "valid", "抖音登录有效"
                elif payload.get("status_code") in (8, 1001):
                    status, message = "invalid", "抖音登录已失效，请重新复制 Cookie"
                else:
                    message = "抖音未返回登录用户，可能需要签名或触发风控，暂时无法确认 Cookie 有效性"
    except BilibiliAccessBlocked as error:
        message = str(error)
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        message = "验证请求失败或平台返回非预期内容，请稍后重试"
    checked = datetime.now(timezone.utc).isoformat()
    # Testing a draft never replaces the saved cookie or its validation result.
    with _edit():
        if value == get_cookie(platform):
            data = _read()
            item = data.setdefault("platforms", {}).setdefault(platform, {})
            item.update(status=status, message=message, last_checked_at=checked)
            _write(data)
    return {"platform": platform, "valid": status == "valid", "status": status, "message": message, "checked_at": checked}
