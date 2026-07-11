"""SQLite-backed background job queue for low-concurrency deployments."""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from config import DB_PATH


ACTIVE_STATUSES = ("queued", "downloading", "transcribing", "generating")
PROCESSING_STATUSES = ("downloading", "transcribing", "generating")
TERMINAL_STATUSES = ("done", "failed", "cancelled")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


@contextmanager
def _db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _owner_clause(user_id: int | None, guest_id: str | None) -> tuple[str, list]:
    if user_id is not None:
        return "user_id = ?", [user_id]
    if guest_id:
        return "guest_id = ?", [guest_id]
    raise ValueError("user_id or guest_id is required")


def _decode_json(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return fallback


def _row_to_job(row: sqlite3.Row | None, queue_position: int | None = None) -> dict | None:
    if row is None:
        return None
    job = dict(row)
    job["task_id"] = job["id"]
    job["stage"] = job["status"]
    job["payload"] = _decode_json(job.pop("payload_json", None), {})
    job["result"] = _decode_json(job.pop("result_json", None), None)
    job["queue_position"] = queue_position
    return job


def create_job(
    url_hash: str,
    url: str,
    *,
    user_id: int | None = None,
    guest_id: str | None = None,
    lang: str = "",
    estimated_seconds: int = 0,
    payload: dict | None = None,
    job_type: str = "whisper",
) -> str:
    """Create a queued job, or return the owner's existing active job ID."""
    owner_sql, owner_params = _owner_clause(user_id, guest_id)
    active_placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
    now = _now()
    job_id = uuid.uuid4().hex[:12]
    with _db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            f"SELECT id FROM background_jobs WHERE {owner_sql} AND url_hash = ? "
            f"AND status IN ({active_placeholders}) ORDER BY created_at LIMIT 1",
            [*owner_params, url_hash, *ACTIVE_STATUSES],
        ).fetchone()
        if existing:
            return existing["id"]
        conn.execute(
            """
            INSERT INTO background_jobs (
                id, job_type, user_id, guest_id, url_hash, url, lang,
                status, progress, message, estimated_seconds, payload_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                job_type,
                user_id,
                guest_id,
                url_hash,
                url,
                lang,
                "等待后台处理",
                max(0, int(estimated_seconds or 0)),
                json.dumps(payload or {}, ensure_ascii=False),
                now,
                now,
            ),
        )
    return job_id


def get_job(
    job_id: str,
    *,
    user_id: int | None = None,
    guest_id: str | None = None,
) -> dict | None:
    params: list = [job_id]
    sql = "SELECT * FROM background_jobs WHERE id = ?"
    if user_id is not None or guest_id:
        owner_sql, owner_params = _owner_clause(user_id, guest_id)
        sql += f" AND {owner_sql}"
        params.extend(owner_params)
    with _db() as conn:
        row = conn.execute(sql, params).fetchone()
        position = _queue_position(conn, row) if row else None
    return _row_to_job(row, position)


def list_active_jobs(
    *, user_id: int | None = None, guest_id: str | None = None
) -> list[dict]:
    owner_sql, owner_params = _owner_clause(user_id, guest_id)
    placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
    with _db() as conn:
        rows = conn.execute(
            f"SELECT * FROM background_jobs WHERE {owner_sql} "
            f"AND status IN ({placeholders}) ORDER BY created_at",
            [*owner_params, *ACTIVE_STATUSES],
        ).fetchall()
        return [_row_to_job(row, _queue_position(conn, row)) for row in rows]


def find_active_job(
    url_hash: str, *, user_id: int | None = None, guest_id: str | None = None
) -> dict | None:
    owner_sql, owner_params = _owner_clause(user_id, guest_id)
    placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
    with _db() as conn:
        row = conn.execute(
            f"SELECT * FROM background_jobs WHERE {owner_sql} AND url_hash = ? "
            f"AND status IN ({placeholders}) ORDER BY created_at LIMIT 1",
            [*owner_params, url_hash, *ACTIVE_STATUSES],
        ).fetchone()
        position = _queue_position(conn, row) if row else None
    return _row_to_job(row, position)


def claim_next_job() -> dict | None:
    """Atomically claim the oldest job when no other job is processing."""
    processing_placeholders = ",".join("?" for _ in PROCESSING_STATUSES)
    now = _now()
    with _db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        running = conn.execute(
            f"SELECT 1 FROM background_jobs WHERE status IN ({processing_placeholders}) LIMIT 1",
            PROCESSING_STATUSES,
        ).fetchone()
        if running:
            return None
        row = conn.execute(
            "SELECT * FROM background_jobs WHERE status = 'queued' "
            "AND cancel_requested = 0 ORDER BY created_at LIMIT 1"
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE background_jobs SET status = 'downloading', progress = 0, "
            "message = ?, started_at = ?, updated_at = ? WHERE id = ? AND status = 'queued'",
            ("正在准备音频", now, now, row["id"]),
        )
        claimed = conn.execute(
            "SELECT * FROM background_jobs WHERE id = ?", (row["id"],)
        ).fetchone()
    return _row_to_job(claimed)


def update_job(job_id: str, **changes) -> bool:
    allowed = {
        "url_hash",
        "url",
        "status",
        "progress",
        "message",
        "error",
        "estimated_seconds",
        "attempts",
        "cancel_requested",
        "payload",
        "result",
    }
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"unsupported job fields: {sorted(unknown)}")
    if not changes:
        return False

    values = dict(changes)
    if "payload" in values:
        values["payload_json"] = json.dumps(values.pop("payload"), ensure_ascii=False)
    if "result" in values:
        values["result_json"] = json.dumps(values.pop("result"), ensure_ascii=False)
    if "progress" in values:
        values["progress"] = max(0, min(100, float(values["progress"])))
    now = _now()
    values["updated_at"] = now
    if values.get("status") in TERMINAL_STATUSES:
        values["completed_at"] = now

    assignments = ", ".join(f"{field} = ?" for field in values)
    with _db() as conn:
        cursor = conn.execute(
            f"UPDATE background_jobs SET {assignments} WHERE id = ?",
            [*values.values(), job_id],
        )
    return cursor.rowcount == 1


def request_cancel(
    job_id: str, *, user_id: int | None = None, guest_id: str | None = None
) -> bool:
    owner_sql, owner_params = _owner_clause(user_id, guest_id)
    now = _now()
    with _db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            f"SELECT status FROM background_jobs WHERE id = ? AND {owner_sql}",
            [job_id, *owner_params],
        ).fetchone()
        if not row or row["status"] in TERMINAL_STATUSES:
            return False
        if row["status"] == "queued":
            conn.execute(
                "UPDATE background_jobs SET status = 'cancelled', progress = 0, "
                "message = ?, cancel_requested = 1, completed_at = ?, updated_at = ? WHERE id = ?",
                ("任务已取消", now, now, job_id),
            )
        else:
            conn.execute(
                "UPDATE background_jobs SET cancel_requested = 1, message = ?, updated_at = ? WHERE id = ?",
                ("正在取消任务", now, job_id),
            )
    return True


def is_cancel_requested(job_id: str) -> bool:
    with _db() as conn:
        row = conn.execute(
            "SELECT cancel_requested FROM background_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    return bool(row and row["cancel_requested"])


def recover_interrupted_jobs() -> int:
    """Requeue interrupted work so it restarts from the beginning."""
    placeholders = ",".join("?" for _ in PROCESSING_STATUSES)
    now = _now()
    with _db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            f"UPDATE background_jobs SET status = 'cancelled', message = ?, "
            f"completed_at = ?, updated_at = ? WHERE status IN ({placeholders}) "
            "AND cancel_requested = 1",
            ["任务已取消", now, now, *PROCESSING_STATUSES],
        )
        cursor = conn.execute(
            f"UPDATE background_jobs SET status = 'queued', progress = 0, "
            f"message = ?, error = NULL, attempts = attempts + 1, cancel_requested = 0, "
            f"started_at = NULL, completed_at = NULL, updated_at = ? "
            f"WHERE status IN ({placeholders})",
            ["服务重启，任务已重新排队并将从头处理", now, *PROCESSING_STATUSES],
        )
    return cursor.rowcount


def _queue_position(conn: sqlite3.Connection, row: sqlite3.Row | None) -> int | None:
    if not row or row["status"] != "queued":
        return None
    result = conn.execute(
        "SELECT COUNT(*) FROM background_jobs WHERE status = 'queued' "
        "AND cancel_requested = 0 AND created_at <= ?",
        (row["created_at"],),
    ).fetchone()
    return int(result[0]) if result else None


def get_queue_position(job_id: str) -> int | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM background_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return _queue_position(conn, row)
