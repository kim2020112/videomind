"""用户认证路由 — 注册/登录/退出/me/guest-sign。"""

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

import time
import threading

from core.auth import (
    create_user, get_user_by_username, verify_password,
    create_session, get_user_by_session, delete_session,
    sign_guest_id, get_today_usage, get_user_by_id,
)
from config import (
    DEFAULT_GUEST_SECRET,
    GUEST_SECRET,
    REGISTRATION_ENABLED,
    USER_DAILY_LIMIT,
    GUEST_DAILY_LIMIT,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_COOKIE = "vm_session"

# ── 简易内存 IP 限流（防 guest-sign 被刷新 device_id 绕过限额）──
_GUEST_SIGN_WINDOW = 3600          # 窗口 1 小时
_GUEST_SIGN_MAX = 20               # 每 IP 每小时最多签发次数
_guest_sign_hits: dict[str, list[float]] = {}
_guest_sign_lock = threading.Lock()


def _check_guest_sign_rate(ip: str) -> bool:
    """滑动窗口限流。返回 True 表示允许。"""
    now = time.time()
    with _guest_sign_lock:
        hits = [t for t in _guest_sign_hits.get(ip, []) if now - t < _GUEST_SIGN_WINDOW]
        if len(hits) >= _GUEST_SIGN_MAX:
            _guest_sign_hits[ip] = hits
            return False
        hits.append(now)
        _guest_sign_hits[ip] = hits
        return True


# ── 依赖：从窗口凭据或 cookie 获取当前用户 ──

def get_request_session_id(request: Request) -> str | None:
    """Resolve an explicit window session before the legacy shared cookie."""
    authorization = request.headers.get("Authorization")
    if authorization is not None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            return token.strip()
        return None

    query_session = request.query_params.get("session_id")
    if query_session is not None:
        return query_session or None

    session_mode = (
        request.headers.get("X-Session-Mode")
        or request.query_params.get("session_mode")
    )
    if session_mode == "guest":
        return None

    return request.cookies.get(SESSION_COOKIE)


def _has_explicit_session(request: Request) -> bool:
    return (
        request.headers.get("Authorization") is not None
        or request.query_params.get("session_id") is not None
        or request.headers.get("X-Session-Mode") == "guest"
        or request.query_params.get("session_mode") == "guest"
    )

def get_current_user(request: Request) -> dict | None:
    session_id = get_request_session_id(request)
    if not session_id:
        return None
    return get_user_by_session(session_id)


def get_identity(request: Request) -> dict:
    """返回 {user_id, guest_id, guest_sig, role, daily_limit}。优先用户，降级游客。"""
    user = get_current_user(request)
    if user:
        limit = user.get("daily_limit", USER_DAILY_LIMIT)
        if user["role"] == "admin":
            limit = 999999
        return {
            "user_id": user["id"],
            "guest_id": None,
            "guest_sig": None,
            "role": user["role"],
            "daily_limit": limit,
        }
    # 游客
    guest_id = request.headers.get("X-Guest-Id", "")
    guest_sig = request.headers.get("X-Guest-Sig", "")
    return {
        "user_id": None,
        "guest_id": guest_id or None,
        "guest_sig": guest_sig or None,
        "role": "guest",
        "daily_limit": GUEST_DAILY_LIMIT,
    }


# ── 请求模型 ──

class AuthRequest(BaseModel):
    username: str
    password: str


class GuestSignRequest(BaseModel):
    device_id: str


# ── 端点 ──

@router.post("/register")
async def register(req: AuthRequest):
    if not REGISTRATION_ENABLED:
        raise HTTPException(403, "注册已关闭，请联系管理员创建账号")
    if len(req.username) < 2 or len(req.password) < 4:
        raise HTTPException(400, "用户名至少2字符，密码至少4字符")
    existing = get_user_by_username(req.username)
    if existing:
        raise HTTPException(409, "用户名已存在")
    user_id = create_user(req.username, req.password)
    session_id = create_session(user_id)
    resp = JSONResponse({"status": "ok", "session_id": session_id})
    resp.set_cookie(
        SESSION_COOKIE, session_id,
        httponly=True, samesite="lax", path="/", max_age=604800,
    )
    return resp


@router.post("/login")
async def login(req: AuthRequest):
    user = get_user_by_username(req.username)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(401, "用户名或密码错误")
    if not user["is_active"] or user["is_deleted"]:
        raise HTTPException(403, "账号已禁用")
    session_id = create_session(user["id"])
    resp = JSONResponse({"status": "ok", "session_id": session_id})
    resp.set_cookie(
        SESSION_COOKIE, session_id,
        httponly=True, samesite="lax", path="/", max_age=604800,
    )
    return resp


@router.post("/logout")
async def logout(request: Request):
    explicit_session = _has_explicit_session(request)
    session_id = get_request_session_id(request)
    if session_id:
        delete_session(session_id)
    resp = Response(
        content='{"status":"ok"}',
        media_type="application/json",
    )
    if not explicit_session:
        resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.get("/me")
async def me(request: Request):
    session_id = get_request_session_id(request)
    identity = get_identity(request)
    from core.auth import check_usage_limit, get_today_usage
    allowed, used, limit = check_usage_limit(
        identity.get("user_id"), identity.get("guest_id"), identity.get("guest_sig")
    )
    if identity["user_id"]:
        user = get_user_by_id(identity["user_id"])
        return {
            "logged_in": True,
            "session_id": session_id,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "role": user["role"],
            },
            "usage": {"used": used, "limit": limit, "allowed": allowed},
        }
    return {
        "logged_in": False,
        "user": None,
        "guest_id": identity.get("guest_id"),
        "usage": {"used": used, "limit": limit, "allowed": allowed},
    }


@router.get("/usage")
async def get_usage(request: Request):
    """轻量级使用次数查询（AI 调用后刷新用）。"""
    identity = get_identity(request)
    from core.auth import check_usage_limit
    allowed, used, limit = check_usage_limit(
        identity.get("user_id"), identity.get("guest_id"), identity.get("guest_sig")
    )
    return {"used": used, "limit": limit, "allowed": allowed}


@router.post("/guest-sign")
async def guest_sign(req: GuestSignRequest, request: Request):
    """为游客 device_id 生成签名。"""
    if not GUEST_SECRET or GUEST_SECRET == DEFAULT_GUEST_SECRET:
        raise HTTPException(503, "游客模式未安全配置，请设置 GUEST_SECRET 或登录后使用")
    if not req.device_id or len(req.device_id) < 8:
        raise HTTPException(400, "无效的 device_id")
    # nginx 反代后 request.client.host 恒为 127.0.0.1，优先取 X-Real-IP
    client_ip = request.headers.get("X-Real-IP") or (request.client.host if request.client else "unknown")
    if not _check_guest_sign_rate(client_ip):
        raise HTTPException(429, "签名请求过于频繁，请稍后再试")
    sig = sign_guest_id(req.device_id)
    return {"signature": sig}
