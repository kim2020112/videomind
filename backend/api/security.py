"""Shared request security helpers for API routes."""

import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import HTTPException, Request

from api.auth_routes import get_current_user, get_identity, get_request_session_id
from config import DEFAULT_GUEST_SECRET, GUEST_SECRET
from core.auth import check_usage_limit, get_user_by_session, verify_guest_id


def guest_signing_enabled() -> bool:
    return bool(GUEST_SECRET) and GUEST_SECRET != DEFAULT_GUEST_SECRET


def require_admin(request: Request) -> dict:
    user = get_current_user(request)
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def require_identity(request: Request) -> dict:
    identity = get_identity(request)
    if identity.get("user_id"):
        return identity

    guest_id = identity.get("guest_id") or request.query_params.get("guest_id")
    guest_sig = identity.get("guest_sig") or request.query_params.get("guest_sig")
    if not guest_signing_enabled():
        raise HTTPException(status_code=403, detail="游客模式未安全配置，请登录后使用")
    if guest_id and verify_guest_id(guest_id, guest_sig or ""):
        identity["guest_id"] = guest_id
        identity["guest_sig"] = guest_sig
        return identity
    raise HTTPException(status_code=403, detail="需要登录或有效游客身份")


def require_usage_allowed(request: Request, action: str = "summary") -> tuple[dict, int, int]:
    identity = require_identity(request)
    allowed, used, limit = check_usage_limit(
        identity.get("user_id"), identity.get("guest_id"), identity.get("guest_sig")
    )
    if not allowed:
        raise HTTPException(status_code=429, detail=f"今日 {action} 次数已用完或身份无效（{used}/{limit}）")
    return identity, used, limit


def require_websocket_identity(websocket) -> dict:
    session_id = get_request_session_id(websocket)
    if session_id:
        user = get_user_by_session(session_id)
        if user:
            limit = user.get("daily_limit")
            if user.get("role") == "admin":
                limit = 999999
            return {
                "user_id": user["id"],
                "guest_id": None,
                "guest_sig": None,
                "role": user["role"],
                "daily_limit": limit,
            }

    guest_id = websocket.query_params.get("guest_id") or websocket.headers.get("X-Guest-Id")
    guest_sig = websocket.query_params.get("guest_sig") or websocket.headers.get("X-Guest-Sig")
    if guest_signing_enabled() and guest_id and verify_guest_id(guest_id, guest_sig or ""):
        return {
            "user_id": None,
            "guest_id": guest_id,
            "guest_sig": guest_sig,
            "role": "guest",
            "daily_limit": None,
        }
    raise HTTPException(status_code=403, detail="需要登录或有效游客身份")


def ensure_public_http_url(url: str) -> None:
    """Allow only public http(s) URLs after DNS resolution."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="仅支持 http/https 链接")
    host = parsed.hostname
    if not host:
        raise HTTPException(status_code=400, detail="无效的 URL")

    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="无法解析目标域名")

    for info in addr_infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise HTTPException(status_code=400, detail="拒绝访问内网地址")


def owns_resource(identity: dict, resource: dict) -> bool:
    if identity.get("user_id") and resource.get("user_id") == identity.get("user_id"):
        return True
    if identity.get("guest_id") and resource.get("guest_id") == identity.get("guest_id"):
        return True
    return False
