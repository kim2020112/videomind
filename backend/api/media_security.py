"""Strict outbound media fetching for the thumbnail and playback proxies."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin, urlsplit

from fastapi import HTTPException


ALLOWED_MEDIA_DOMAINS = frozenset({
    "xhscdn.com",
    "hdslb.com",
    "bilivideo.com",
    "bilibili.com",
    "douyinvod.com",
    "365yg.com",
    "amemv.com",
    "pstatp.com",
    "ixigua.com",
    "ytimg.com",
    "googlevideo.com",
    "youtube.com",
})

CDN_REFERERS = {
    "xhscdn.com": "https://www.xiaohongshu.com/",
    "hdslb.com": "https://www.bilibili.com/",
    "bilivideo.com": "https://www.bilibili.com/",
    "bilibili.com": "https://www.bilibili.com/",
    "douyinvod.com": "https://www.douyin.com/",
    "365yg.com": "https://www.douyin.com/",
    "amemv.com": "https://www.douyin.com/",
    "pstatp.com": "https://www.douyin.com/",
    "ixigua.com": "https://www.ixigua.com/",
    "ytimg.com": "https://www.youtube.com/",
    "googlevideo.com": "https://www.youtube.com/",
    "youtube.com": "https://www.youtube.com/",
}

THUMBNAIL_CONTENT_TYPES = frozenset({
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/avif",
})
THUMBNAIL_MAX_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 3
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MEDIA_RESPONSE_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; sandbox",
}

Resolver = Callable[..., list]


@dataclass(frozen=True)
class ValidatedMediaTarget:
    url: str
    host: str
    port: int
    request_target: str
    addresses: tuple


Opener = Callable[[ValidatedMediaTarget, dict[str, str]], object]


@dataclass
class ThumbnailPayload:
    content: bytes
    content_type: str


@dataclass
class OpenedMedia:
    response: object
    content_type: str
    status: int
    url: str

    def close(self) -> None:
        self.response.close()


class _ConnectionBoundResponse:
    def __init__(self, response, connection):
        self._response = response
        self._connection = connection
        self.status = response.status
        self.headers = response.headers

    def getheader(self, name, default=None):
        return self._response.getheader(name, default)

    def read(self, amount=-1):
        return self._response.read(amount)

    def close(self):
        try:
            self._response.close()
        finally:
            self._connection.close()


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def _allowed_domain(host: str) -> str | None:
    return next((domain for domain in ALLOWED_MEDIA_DOMAINS if _host_matches(host, domain)), None)


def _is_public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return address.is_global and not address.is_multicast


def validate_media_url(url: str, *, resolver: Resolver | None = None):
    """Validate scheme, host allowlist, and every resolved address."""
    resolver = resolver or socket.getaddrinfo
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https":
        raise HTTPException(status_code=400, detail="媒体代理仅支持 HTTPS")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="媒体 URL 不允许包含凭据")

    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or _allowed_domain(host) is None:
        raise HTTPException(status_code=400, detail="媒体域名不在允许列表中")
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="无效的媒体 URL 端口") from exc

    try:
        addresses = resolver(host, port, type=socket.SOCK_STREAM)
    except (OSError, socket.gaierror) as exc:
        raise HTTPException(status_code=400, detail="无法解析媒体域名") from exc
    if not addresses:
        raise HTTPException(status_code=400, detail="无法解析媒体域名")
    if any(not _is_public_address(info[4][0]) for info in addresses):
        raise HTTPException(status_code=400, detail="拒绝访问非公网媒体地址")
    request_target = parsed.path or "/"
    if parsed.query:
        request_target = f"{request_target}?{parsed.query}"
    return ValidatedMediaTarget(
        url=url,
        host=host,
        port=port,
        request_target=request_target,
        addresses=tuple(addresses),
    )


def referer_for_url(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    domain = next((item for item in CDN_REFERERS if _host_matches(host, item)), None)
    return CDN_REFERERS.get(domain) if domain else None


def _default_opener(target: ValidatedMediaTarget, headers: dict[str, str]):
    context = ssl.create_default_context()
    last_error = None
    for family, socktype, proto, _, sockaddr in target.addresses:
        raw_socket = None
        tls_socket = None
        connection = None
        try:
            raw_socket = socket.socket(family, socktype, proto)
            raw_socket.settimeout(30)
            raw_socket.connect(sockaddr)
            tls_socket = context.wrap_socket(raw_socket, server_hostname=target.host)
            raw_socket = None

            connection = http.client.HTTPSConnection(
                target.host,
                port=target.port,
                timeout=30,
                context=context,
            )
            connection.sock = tls_socket
            tls_socket = None
            request_headers = dict(headers)
            request_headers.setdefault(
                "Host",
                target.host if target.port == 443 else f"{target.host}:{target.port}",
            )
            connection.request("GET", target.request_target, headers=request_headers)
            return _ConnectionBoundResponse(connection.getresponse(), connection)
        except Exception as exc:
            last_error = exc
            if connection is not None:
                connection.close()
            elif tls_socket is not None:
                tls_socket.close()
            elif raw_socket is not None:
                raw_socket.close()
    if last_error is not None:
        raise last_error
    raise OSError("媒体域名没有可连接的公网地址")


def _header(response, name: str, default=None):
    getter = getattr(response, "getheader", None)
    if getter:
        return getter(name, default)
    headers = getattr(response, "headers", {})
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return default


def _close(response) -> None:
    try:
        response.close()
    except Exception:
        pass


def _open_checked(
    url: str,
    headers: dict[str, str],
    *,
    resolver: Resolver,
    opener: Opener,
) -> tuple[object, str]:
    current_url = url
    redirects = 0
    while True:
        target = validate_media_url(current_url, resolver=resolver)
        try:
            response = opener(target, headers)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"媒体源请求失败: {exc}") from exc

        status = int(getattr(response, "status", 0) or 0)
        if status not in REDIRECT_STATUSES:
            if status not in (200, 206):
                _close(response)
                raise HTTPException(status_code=502, detail=f"媒体源返回异常状态: {status}")
            return response, current_url

        location = _header(response, "Location")
        _close(response)
        if not location:
            raise HTTPException(status_code=502, detail="媒体源重定向缺少 Location")
        if redirects >= MAX_REDIRECTS:
            raise HTTPException(status_code=502, detail="媒体源重定向次数过多")
        redirects += 1
        current_url = urljoin(current_url, location)


def _normalized_content_type(response) -> str:
    raw = str(_header(response, "Content-Type", "") or "")
    return raw.split(";", 1)[0].strip().lower()


def fetch_thumbnail(
    url: str,
    headers: dict[str, str] | None = None,
    *,
    resolver: Resolver | None = None,
    opener: Opener | None = None,
) -> ThumbnailPayload:
    resolver = resolver or socket.getaddrinfo
    opener = opener or _default_opener
    response, _ = _open_checked(
        url,
        dict(headers or {}),
        resolver=resolver,
        opener=opener,
    )
    try:
        content_type = _normalized_content_type(response)
        if content_type not in THUMBNAIL_CONTENT_TYPES:
            raise HTTPException(status_code=415, detail="缩略图类型不受支持")

        raw_length = _header(response, "Content-Length")
        if raw_length:
            try:
                if int(raw_length) > THUMBNAIL_MAX_BYTES:
                    raise HTTPException(status_code=413, detail="缩略图超过 10 MiB 限制")
            except ValueError:
                pass

        chunks = []
        size = 0
        while True:
            chunk = response.read(min(65536, THUMBNAIL_MAX_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > THUMBNAIL_MAX_BYTES:
                raise HTTPException(status_code=413, detail="缩略图超过 10 MiB 限制")
        return ThumbnailPayload(content=b"".join(chunks), content_type=content_type)
    finally:
        _close(response)


def open_video(
    url: str,
    headers: dict[str, str] | None = None,
    *,
    resolver: Resolver | None = None,
    opener: Opener | None = None,
) -> OpenedMedia:
    resolver = resolver or socket.getaddrinfo
    opener = opener or _default_opener
    response, final_url = _open_checked(
        url,
        dict(headers or {}),
        resolver=resolver,
        opener=opener,
    )
    content_type = _normalized_content_type(response)
    if not (
        content_type.startswith("video/")
        or content_type.startswith("audio/")
        or content_type == "application/octet-stream"
    ):
        _close(response)
        raise HTTPException(status_code=415, detail="媒体流类型不受支持")
    return OpenedMedia(
        response=response,
        content_type=content_type,
        status=int(getattr(response, "status", 200) or 200),
        url=final_url,
    )
