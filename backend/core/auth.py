"""用户认证、Session 管理、使用次数统计。"""

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone

from passlib.hash import bcrypt

from config import (
    ADMIN_USERNAME, ADMIN_PASSWORD, GUEST_SECRET,
    GUEST_DAILY_LIMIT, USER_DAILY_LIMIT,
)
from database import get_db
from core.logging_config import get_logger

logger = get_logger(__name__)

# ── 密码 ──

def hash_password(password: str) -> str:
    return bcrypt.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.verify(password, hashed)


# ── Session ──

def create_session(user_id: int) -> str:
    """创建 session，返回 session_id。"""
    session_id = str(uuid.uuid4())
    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, expires_at) VALUES (?, ?, ?)",
            (session_id, user_id, expires_at),
        )
    return session_id


def get_user_by_session(session_id: str) -> dict | None:
    """通过 session_id 获取用户信息。过期 session 自动删除。"""
    with get_db() as conn:
        now = datetime.now(timezone.utc).isoformat()
        row = conn.execute("""
            SELECT u.id, u.username, u.role, u.daily_limit, u.is_active, u.is_deleted
            FROM sessions s JOIN users u ON s.user_id = u.id
            WHERE s.id = ? AND s.expires_at > ? AND u.is_active = 1 AND u.is_deleted = 0
        """, (session_id, now)).fetchone()
        if not row:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return None
        return dict(row)


def delete_session(session_id: str):
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def cleanup_expired_sessions():
    with get_db() as conn:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))


# ── 用户 CRUD ──

def create_user(username: str, password: str, role: str = "user") -> int:
    """创建用户，返回 user_id。"""
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, hash_password(password), role),
        )
        return cursor.lastrowid


def get_user_by_username(username: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? AND is_deleted = 0", (username,)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ? AND is_deleted = 0", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def ensure_admin():
    """启动时确保 admin 用户存在（从 env 读取凭据）。"""
    if not ADMIN_PASSWORD:
        return
    existing = get_user_by_username(ADMIN_USERNAME)
    if existing:
        return
    create_user(ADMIN_USERNAME, ADMIN_PASSWORD, role="admin")
    logger.info(f"Admin 用户已创建: {ADMIN_USERNAME}")


# ── 游客签名 ──

def sign_guest_id(device_id: str) -> str:
    return hmac.new(
        GUEST_SECRET.encode(), device_id.encode(), hashlib.sha256
    ).hexdigest()[:16]


def verify_guest_id(device_id: str, signature: str) -> bool:
    if not device_id or not signature:
        return False
    return hmac.compare_digest(sign_guest_id(device_id), signature)


# ── 使用次数（统一入口）──

def check_usage_limit(user_id: int = None, guest_id: str = None, guest_sig: str = None) -> tuple[bool, int, int]:
    """检查 AI 使用次数。返回 (allowed, used, limit)。"""
    if user_id:
        user = get_user_by_id(user_id)
        if not user:
            return (False, 0, 0)
        if user["role"] == "admin":
            return (True, 0, 999999)
        limit = user["daily_limit"] or USER_DAILY_LIMIT
        used = get_today_usage(user_id=user_id)
        return (used < limit, used, limit)
    elif guest_id:
        if not verify_guest_id(guest_id, guest_sig or ""):
            return (False, 0, 0)
        used = get_today_usage(guest_id=guest_id)
        return (used < GUEST_DAILY_LIMIT, used, GUEST_DAILY_LIMIT)
    return (False, 0, 0)


def log_usage(user_id: int = None, guest_id: str = None, action: str = "summary", status: str = "SUCCESS"):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO usage_logs (user_id, guest_id, action, status) VALUES (?, ?, ?, ?)",
            (user_id, guest_id, action, status),
        )


def get_today_usage(user_id: int = None, guest_id: str = None) -> int:
    """获取今日 AI 使用次数（只计 SUCCESS，CACHE_HIT 不计入）。"""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
    with get_db() as conn:
        if user_id:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM usage_logs WHERE user_id = ? AND created_at >= ? AND status = 'SUCCESS'",
                (user_id, today_start),
            ).fetchone()
        elif guest_id:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM usage_logs WHERE guest_id = ? AND created_at >= ? AND status = 'SUCCESS'",
                (guest_id, today_start),
            ).fetchone()
        else:
            return 0
        return row[0] if row else 0


# ── 用户历史（写入，供 stream_routes 调用）──

def add_user_history(user_id: int = None, guest_id: str = None,
                     url_hash: str = "", url: str = "",
                     title: str = "", platform: str = ""):
    with get_db() as conn:
        if user_id:
            conn.execute(
                "INSERT OR IGNORE INTO user_history (user_id, url_hash, url, video_title, platform) VALUES (?, ?, ?, ?, ?)",
                (user_id, url_hash, url, title, platform),
            )
        elif guest_id:
            conn.execute(
                "INSERT OR IGNORE INTO user_history (guest_id, url_hash, url, video_title, platform) VALUES (?, ?, ?, ?, ?)",
                (guest_id, url_hash, url, title, platform),
            )
