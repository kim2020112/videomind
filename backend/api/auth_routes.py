"""用户认证路由 — 注册/登录/退出/me/guest-sign。"""

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from typing import Optional

from core.auth import (
    create_user, get_user_by_username, verify_password,
    create_session, get_user_by_session, delete_session,
    sign_guest_id, get_today_usage, get_user_by_id,
)
from config import REGISTRATION_ENABLED, USER_DAILY_LIMIT, GUEST_DAILY_LIMIT

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_COOKIE = "vm_session"


# ── 依赖：从 cookie 获取当前用户 ──

def get_current_user(request: Request) -> dict | None:
    session_id = request.cookies.get(SESSION_COOKIE)
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
    resp = Response(
        content='{"status":"ok"}',
        media_type="application/json",
    )
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
    resp = Response(
        content='{"status":"ok"}',
        media_type="application/json",
    )
    resp.set_cookie(
        SESSION_COOKIE, session_id,
        httponly=True, samesite="lax", path="/", max_age=604800,
    )
    return resp


@router.post("/logout")
async def logout(request: Request):
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        delete_session(session_id)
    resp = Response(
        content='{"status":"ok"}',
        media_type="application/json",
    )
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.get("/me")
async def me(request: Request):
    identity = get_identity(request)
    from core.auth import check_usage_limit, get_today_usage
    allowed, used, limit = check_usage_limit(
        identity.get("user_id"), identity.get("guest_id"), identity.get("guest_sig")
    )
    if identity["user_id"]:
        user = get_user_by_id(identity["user_id"])
        return {
            "logged_in": True,
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
async def guest_sign(req: GuestSignRequest):
    """为游客 device_id 生成签名。"""
    if not req.device_id or len(req.device_id) < 8:
        raise HTTPException(400, "无效的 device_id")
    sig = sign_guest_id(req.device_id)
    return {"signature": sig}
