"""B 站凭据隔离与受保护的 yt-dlp 入口。默认仅登录相关 API 使用 Cookie。"""

from __future__ import annotations

import atexit
import os
import tempfile
import threading
import time
import io
import json
from contextlib import contextmanager, nullcontext

from core.video import is_bilibili_video
from core.bilibili_guard import (
    BilibiliAccessBlocked, assert_allowed, check_response,
    is_bilibili_url, request_kind, request_scope, request_slot,
)
from urllib.parse import urlparse, urljoin

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
BILIBILI_REFERER = "https://www.bilibili.com/"

_cookiefile_path: str | None = None
_cookiefile_lock = threading.Lock()
_cookiefile_value = None


LOGIN_API_PATHS = frozenset({
    '/x/web-interface/nav', '/x/space/wbi/arc/search',
    '/x/player/v2', '/x/player/wbi/v2', '/x/v2/dm/view',
    '/x/web-interface/view', '/x/player/pagelist',
})


def default_cookie() -> str:
    """Configured credentials for login-dependent metadata, unless opted out."""
    if os.getenv('BILIBILI_USE_ACCOUNT_COOKIE', 'true').lower() != 'true':
        return ''
    from core.platform_config import get_cookie
    return get_cookie('bilibili')


def cookie_for_url(url: str) -> str:
    """Attach credentials only to HTTPS and explicitly selected Bilibili APIs."""
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        return ''
    if parsed.scheme != 'https' or not (host == 'bilibili.com' or host.endswith('.bilibili.com')):
        return ''
    if os.getenv('BILIBILI_COOKIE_SCOPE', 'metadata') == 'all':
        return default_cookie()
    if host == 'api.bilibili.com' and parsed.path in LOGIN_API_PATHS:
        return default_cookie()
    return ''


def _cleanup_cookiefile(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _cookiefile() -> str:
    """把 Cookie 写成 Netscape 文件（.bilibili.com 域），进程退出时清理。"""
    global _cookiefile_path, _cookiefile_value
    with _cookiefile_lock:
        cookie = default_cookie() if os.getenv("BILIBILI_COOKIE_SCOPE", "metadata") == "all" else ""
        if _cookiefile_path and _cookiefile_value == cookie and os.path.isfile(_cookiefile_path):
            return _cookiefile_path
        fd, path = tempfile.mkstemp(prefix="videomind_bili_", suffix=".txt")
        os.chmod(path, 0o600)
        expiry = int(time.time()) + 30 * 86400
        lines = ["# Netscape HTTP Cookie File", "# generated from BILIBILI_COOKIE"]
        for part in cookie.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            name, value = part.split("=", 1)
            name, value = name.strip(), value.strip()
            if name:
                lines.append(f".bilibili.com\tTRUE\t/\tTRUE\t{expiry}\t{name}\t{value}")
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        atexit.register(_cleanup_cookiefile, path)
        _cookiefile_path = path
        _cookiefile_value = cookie
        return path


def ydl_opts_for(url: str = "", *more_urls: str) -> dict:
    """B 站只允许串行下载，关闭所有内部自动重试。"""
    if not any(is_bilibili_video(u) for u in (url, *more_urls)):
        if any((urlparse(u).hostname or "").endswith(".douyin.com") or urlparse(u).hostname == "douyin.com" for u in (url, *more_urls)):
            from core.platform_config import get_cookie
            cookie = get_cookie("douyin")
            if cookie:
                return {"cookiefile": _douyin_cookiefile(cookie), "http_headers": {"User-Agent": USER_AGENT, "Referer": "https://www.douyin.com/"}}
        return {}
    return {
        "retries": 0,
        "fragment_retries": 0,
        "extractor_retries": 0,
        "file_access_retries": 0,
        "concurrent_fragment_downloads": 1,
        "socket_timeout": 15,
        "hls_prefer_native": True,
        "cookiefile": _cookiefile(),
        "http_headers": {
            "User-Agent": USER_AGENT,
            "Referer": BILIBILI_REFERER,
        },
    }


def ytdlp_error_message(err: BaseException) -> str:
    """把 yt-dlp 报错翻译成用户可操作的提示。"""
    text = str(err)
    lowered = text.lower()
    if any(f"http error {code}" in lowered for code in (403, 412, 429)) or "412: precondition failed" in lowered:
        return "B 站限制了请求，已停止访问；请使用已有缓存或官方客户端，不要通过更换 Cookie 反复重试"
    if (
        "deleted or geo-restricted" in lowered
        or "private video" in lowered
        or "video does not exist" in lowered
        or "this video is unavailable" in lowered
    ):
        return "视频不存在、已删除或属于付费/专属内容（如 B 站课堂课程），暂不支持解析"
    if "login" in lowered and ("required" in lowered or "cookie" in lowered):
        return "该视频需要登录权限，自动访问已停止；请在 B 站官方客户端观看"
    return text


def _douyin_cookiefile(cookie: str) -> str:
    """Scope cookies to Douyin domains, including short-link resolution."""
    fd, path = tempfile.mkstemp(prefix="videomind_douyin_", suffix=".txt")
    with os.fdopen(fd, "w") as stream:
        stream.write("# Netscape HTTP Cookie File\n")
        for part in cookie.split(";"):
            if "=" not in part:
                continue
            name, value = part.strip().split("=", 1)
            stream.write(f".douyin.com\tTRUE\t/\tTRUE\t0\t{name.strip()}\t{value.strip()}\n")
    atexit.register(_cleanup_cookiefile, path)
    return path


@contextmanager
def youtube_dl(options: dict, *source_urls: str):
    """Inspect each HTTP hop before allowing extractors to proceed or fall back."""
    import yt_dlp
    from yt_dlp.networking import Request
    from yt_dlp.networking.common import Response
    from yt_dlp.networking.exceptions import HTTPError
    from yt_dlp.compat import urllib_req_to_req
    from core.bilibili_transport import install_single_hop_transport

    protected_source = any(is_bilibili_url(url) for url in source_urls if url)
    if protected_source:
        assert_allowed()
    if protected_source:
        options = {**options, 'retries': 0, 'fragment_retries': 0, 'extractor_retries': 0,
                   'concurrent_fragment_downloads': 1, 'external_downloader': None}
    with yt_dlp.YoutubeDL(options) as ydl:
        install_single_hop_transport(ydl)
        original_open = ydl.urlopen
        original_download = ydl.dl

        def guarded_download(name, info, *args, **kwargs):
            targets = info.get('requested_formats') or [info]
            if protected_source or any(is_bilibili_url(f.get('url', '')) for f in targets):
                from yt_dlp.utils import determine_protocol
                from yt_dlp.downloader import get_suitable_downloader
                from yt_dlp.downloader.http import HttpFD
                from yt_dlp.downloader.dash import DashSegmentsFD
                # External downloaders can spawn a network-capable ffmpeg that
                # cannot participate in this guard. Keep local mux/transcode.
                if (info.get('is_live') or info.get('section_start') is not None or info.get('section_end') is not None
                        or ydl.params.get('external_downloader')
                        or any(f.get('is_live') or determine_protocol(f) not in ('http', 'https', 'http_dash_segments') for f in targets)
                        or any(get_suitable_downloader({**info, **f}, ydl.params) not in (HttpFD, DashSegmentsFD) for f in targets)):
                    raise BilibiliAccessBlocked("B 站仅支持受保护的普通视频下载；直播或此流媒体格式请在官方客户端观看")
                assert_allowed()
            return original_download(name, info, *args, **kwargs)

        def prune_account_cookies():
            if os.getenv('BILIBILI_COOKIE_SCOPE', 'metadata') == 'all' and os.getenv('BILIBILI_USE_ACCOUNT_COOKIE', 'true').lower() == 'true':
                return
            # Retain anonymous device cookies, never persist a newly issued
            # account session in the shared metadata-only cookie file.
            allowed = {'buvid3', 'buvid4', 'b_nut', 'buvid_fp', '_uuid', 'b_lsid'}
            jar = getattr(ydl, 'cookiejar', ())
            for cookie in list(jar):
                if cookie.domain.lstrip('.') == 'bilibili.com' or cookie.domain.endswith('.bilibili.com'):
                    if cookie.name not in allowed:
                        jar.clear(cookie.domain, cookie.path, cookie.name)

        prune_account_cookies()

        def guarded_open(request):
            if isinstance(request, str):
                current = Request(request)
            elif isinstance(request, Request):
                current = request.copy()
            else:
                current = urllib_req_to_req(request)
            for hop in range(6):
                url = current.url
                guarded = protected_source or is_bilibili_url(url)
                kind = request_kind(url)
                scope = request_scope(url)
                # Cookie jars are domain scoped; never forward explicit account
                # headers to a CDN or another host via a redirect.
                if guarded:
                    current.headers.pop('Cookie', None)
                    current.headers.pop('Authorization', None)
                    account_cookie = cookie_for_url(url)
                    if account_cookie:
                        current.headers['Cookie'] = account_cookie
                prune_account_cookies()
                with request_slot(kind, scope) if guarded else nullcontext():
                    try:
                        try:
                            response = original_open(current)
                        finally:
                            prune_account_cookies()
                    except HTTPError as exc:
                        response = exc.response
                        if response.status not in (301, 302, 303, 307, 308):
                            try:
                                if guarded:
                                    check_response(response.status, kind=kind, scope=scope, retry_after=response.headers.get("Retry-After"))
                            finally:
                                response.close()
                            raise
                    try:
                        if guarded:
                            check_response(response.status, kind=kind, scope=scope, retry_after=response.headers.get("Retry-After"))
                        if response.status in (301, 302, 303, 307, 308):
                            location = response.headers.get('Location')
                            if not location or hop == 5:
                                raise BilibiliAccessBlocked("链接重定向异常，已停止访问")
                            next_url = urljoin(url, location)
                            if guarded and urlparse(url).scheme == 'https' and urlparse(next_url).scheme == 'http':
                                raise BilibiliAccessBlocked("B 站链接重定向至非加密地址，已停止访问")
                            if urlparse(next_url).scheme not in ('http', 'https'):
                                raise BilibiliAccessBlocked("链接重定向协议不受支持，已停止访问")
                            if urlparse(next_url).netloc != urlparse(url).netloc:
                                current.headers.pop('Cookie', None)
                                current.headers.pop('Authorization', None)
                            if response.status in (301, 302, 303) and current.method != 'HEAD':
                                current.method = 'GET'
                                current.data = None
                                current.headers.pop('Content-Type', None)
                                current.headers.pop('Content-Length', None)
                            current.url = next_url
                            response.close()
                            continue
                        if (urlparse(url).hostname or '').lower() == 'api.bilibili.com':
                            body = response.read()
                            try:
                                payload = json.loads(body)
                            except (ValueError, UnicodeDecodeError):
                                payload = None
                            check_response(response.status, payload, kind=kind, scope=scope)
                            buffered = Response(io.BytesIO(body), response.url, dict(response.headers), response.status)
                            response.close()
                            return buffered
                        return response
                    except BaseException:
                        response.close()
                        raise

        ydl.urlopen = guarded_open
        ydl.dl = guarded_download
        try:
            yield ydl
        finally:
            prune_account_cookies()
