"""blogger_* 表读写。共享目录（creator/video/page/sync）与按身份订阅（subs）分离。"""

from __future__ import annotations

import copy
from datetime import datetime, timezone

from database import get_db


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


now_iso = _now


def _owner_clause(identity: dict) -> tuple[str, list]:
    if identity.get("user_id"):
        return "user_id = ?", [identity["user_id"]]
    if identity.get("guest_id"):
        return "guest_id = ?", [identity["guest_id"]]
    raise ValueError("user_id or guest_id is required")


def _row_to_dict(row) -> dict | None:
    return dict(row) if row is not None else None


# ── creators（共享） ──

def upsert_creator(platform: str, uid: str, *, name: str = "", avatar: str = "",
                   follower_count: int = 0) -> int:
    now = _now()
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, name, avatar, follower_count FROM blogger_creators WHERE platform = ? AND uid = ?",
            (platform, uid),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE blogger_creators SET name = ?, avatar = ?, follower_count = ?, "
                "updated_at = ? WHERE id = ?",
                (name or row["name"], avatar or row["avatar"],
                 follower_count or row["follower_count"], now, row["id"]),
            )
            return row["id"]
        cursor = conn.execute(
            "INSERT INTO blogger_creators (platform, uid, name, avatar, follower_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (platform, uid, name, avatar, follower_count, now, now),
        )
        return cursor.lastrowid


def get_creator(creator_id: int) -> dict | None:
    with get_db() as conn:
        return _row_to_dict(conn.execute(
            "SELECT * FROM blogger_creators WHERE id = ?", (creator_id,)
        ).fetchone())


def touch_creator_synced(creator_id: int, video_count: int | None = None) -> None:
    now = _now()
    with get_db() as conn:
        if video_count is None:
            conn.execute(
                "UPDATE blogger_creators SET last_synced_at = ?, updated_at = ? WHERE id = ?",
                (now, now, creator_id),
            )
        else:
            conn.execute(
                "UPDATE blogger_creators SET last_synced_at = ?, video_count = ?, updated_at = ? WHERE id = ?",
                (now, video_count, now, creator_id),
            )


# ── subs（按身份） ──

def upsert_sub(creator_id: int, identity: dict, *, alias: str = "") -> int:
    """幂等订阅：同身份同 creator 返回既有 sub_id。"""
    owner_sql, owner_params = _owner_clause(identity)
    now = _now()
    with get_db() as conn:
        row = conn.execute(
            f"SELECT id FROM blogger_subs WHERE creator_id = ? AND {owner_sql}",
            [creator_id, *owner_params],
        ).fetchone()
        if row:
            return row["id"]
        columns = ["creator_id", "alias", "created_at"]
        values: list = [creator_id, alias, now]
        if identity.get("user_id"):
            columns.append("user_id")
            values.append(identity["user_id"])
        else:
            columns.append("guest_id")
            values.append(identity["guest_id"])
        placeholders = ", ".join("?" for _ in values)
        cursor = conn.execute(
            f"INSERT INTO blogger_subs ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
        return cursor.lastrowid


def get_sub(sub_id: int, identity: dict | None = None) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT s.*, c.platform, c.uid, c.name, c.avatar, c.follower_count, c.video_count, "
            "c.last_synced_at FROM blogger_subs s "
            "JOIN blogger_creators c ON c.id = s.creator_id WHERE s.id = ?",
            (sub_id,),
        ).fetchone()
        if row is None:
            return None
        item = dict(row)
        if identity is not None:
            if identity.get("user_id") and item.get("user_id") != identity.get("user_id"):
                return None
            if not identity.get("user_id") and item.get("guest_id") != identity.get("guest_id"):
                return None
        return item


def list_subs(identity: dict) -> list[dict]:
    owner_sql, owner_params = _owner_clause(identity)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT s.id, s.creator_id, s.alias, s.created_at, "
            "c.platform, c.uid, c.name, c.avatar, c.follower_count, c.video_count, c.last_synced_at, "
            "(SELECT COUNT(*) FROM blogger_videos v WHERE v.creator_id = c.id) AS catalog_count, "
            "(SELECT status FROM blogger_syncs y WHERE y.creator_id = c.id "
            " ORDER BY y.created_at DESC, y.id DESC LIMIT 1) AS sync_status, "
            "(SELECT error_code FROM blogger_syncs y WHERE y.creator_id = c.id "
            " ORDER BY y.created_at DESC, y.id DESC LIMIT 1) AS sync_error_code, "
            "(SELECT error FROM blogger_syncs y WHERE y.creator_id = c.id "
            " ORDER BY y.created_at DESC, y.id DESC LIMIT 1) AS sync_error, "
            "(SELECT mode FROM blogger_syncs y WHERE y.creator_id = c.id "
            " ORDER BY y.created_at DESC, y.id DESC LIMIT 1) AS sync_mode, "
            "(SELECT page FROM blogger_syncs y WHERE y.creator_id = c.id "
            " ORDER BY y.created_at DESC, y.id DESC LIMIT 1) AS sync_page, "
            "(SELECT found FROM blogger_syncs y WHERE y.creator_id = c.id "
            " ORDER BY y.created_at DESC, y.id DESC LIMIT 1) AS sync_found, "
            "(SELECT expected FROM blogger_syncs y WHERE y.creator_id = c.id "
            " ORDER BY y.created_at DESC, y.id DESC LIMIT 1) AS sync_expected, "
            "(SELECT added FROM blogger_syncs y WHERE y.creator_id = c.id "
            " ORDER BY y.created_at DESC, y.id DESC LIMIT 1) AS sync_added "
            f"FROM blogger_subs s JOIN blogger_creators c ON c.id = s.creator_id "
            f"WHERE s.{owner_sql} ORDER BY s.created_at DESC, s.id DESC",
            owner_params,
        ).fetchall()
        return [dict(row) for row in rows]


def update_sub(sub_id: int, identity: dict, *, alias: str) -> bool:
    """只改用户备注名；同步刷新远端昵称时不动 alias。"""
    sub = get_sub(sub_id, identity)
    if not sub:
        return False
    with get_db() as conn:
        conn.execute("UPDATE blogger_subs SET alias = ? WHERE id = ?", (alias, sub_id))
    return True


def remove_sub(sub_id: int, identity: dict) -> dict:
    """退订：只删自己的 sub。最后一个订阅者离开且无活跃批次/同步时级联清共享目录。"""
    sub = get_sub(sub_id, identity)
    if not sub:
        return {"removed": False, "cascade": False}
    creator_id = sub["creator_id"]
    with get_db() as conn:
        conn.execute("DELETE FROM blogger_subs WHERE id = ?", (sub_id,))
        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM blogger_subs WHERE creator_id = ?", (creator_id,)
        ).fetchone()["n"]
        if remaining > 0:
            return {"removed": True, "cascade": False}
        active = conn.execute(
            "SELECT COUNT(*) AS n FROM blogger_syncs WHERE creator_id = ? "
            "AND status IN ('queued', 'running')",
            (creator_id,),
        ).fetchone()["n"]
        active += conn.execute(
            "SELECT COUNT(*) AS n FROM blogger_batches WHERE creator_id = ? "
            "AND status IN ('queued', 'running')",
            (creator_id,),
        ).fetchone()["n"]
        if active > 0:
            return {"removed": True, "cascade": False}
        conn.execute("DELETE FROM blogger_video_pages WHERE video_id IN "
                     "(SELECT id FROM blogger_videos WHERE creator_id = ?)", (creator_id,))
        conn.execute("DELETE FROM blogger_videos WHERE creator_id = ?", (creator_id,))
        conn.execute("DELETE FROM blogger_syncs WHERE creator_id = ?", (creator_id,))
        # 批次条目随批次级联删；学习内容（user_history/ai_cache）保留
        conn.execute(
            "DELETE FROM blogger_batch_items WHERE batch_id IN "
            "(SELECT id FROM blogger_batches WHERE creator_id = ?)",
            (creator_id,),
        )
        conn.execute("DELETE FROM blogger_batches WHERE creator_id = ?", (creator_id,))
        conn.execute("DELETE FROM blogger_creators WHERE id = ?", (creator_id,))
    return {"removed": True, "cascade": True}


# ── videos / pages（共享目录） ──

def upsert_video(creator_id: int, entry: dict) -> int:
    bvid = entry.get("bvid") or ""
    if not bvid:
        raise ValueError("bvid is required")
    now = _now()
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM blogger_videos WHERE bvid = ?", (bvid,)
        ).fetchone()
        if row:
            # 空值保护：arc/search 少字段时不抹掉已有的非空元数据
            conn.execute(
                "UPDATE blogger_videos SET "
                "title = CASE WHEN ? != '' THEN ? ELSE title END, "
                "cover = CASE WHEN ? != '' THEN ? ELSE cover END, "
                "description = CASE WHEN ? != '' THEN ? ELSE description END, "
                "published_at = CASE WHEN ? > 0 THEN ? ELSE published_at END, "
                "duration = CASE WHEN ? > 0 THEN ? ELSE duration END, "
                "last_seen_at = ? WHERE id = ?",
                (
                    entry.get("title") or "", entry.get("title") or "",
                    entry.get("cover") or "", entry.get("cover") or "",
                    entry.get("description") or "", entry.get("description") or "",
                    int(entry.get("published_at") or 0), int(entry.get("published_at") or 0),
                    int(entry.get("duration") or 0), int(entry.get("duration") or 0),
                    now,
                    row["id"],
                ),
            )
            return row["id"]
        cursor = conn.execute(
            "INSERT INTO blogger_videos "
            "(creator_id, bvid, title, cover, description, published_at, duration, last_seen_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                creator_id,
                bvid,
                entry.get("title") or "",
                entry.get("cover") or "",
                entry.get("description") or "",
                int(entry.get("published_at") or 0),
                int(entry.get("duration") or 0),
                now,
                now,
            ),
        )
        return cursor.lastrowid


def get_video(video_id: int) -> dict | None:
    with get_db() as conn:
        return _row_to_dict(conn.execute(
            "SELECT * FROM blogger_videos WHERE id = ?", (video_id,)
        ).fetchone())


def get_video_by_bvid(bvid: str) -> dict | None:
    with get_db() as conn:
        return _row_to_dict(conn.execute(
            "SELECT * FROM blogger_videos WHERE bvid = ?", (bvid,)
        ).fetchone())


def delete_video_by_bvid(bvid: str) -> bool:
    """删除目录视频及其分P缓存（如误收的课堂推广条目）。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM blogger_videos WHERE bvid = ?", (bvid,)
        ).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM blogger_video_pages WHERE video_id = ?", (row["id"],))
        conn.execute("DELETE FROM blogger_videos WHERE id = ?", (row["id"],))
        return True


def known_bvids(creator_id: int) -> set[str]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT bvid FROM blogger_videos WHERE creator_id = ?", (creator_id,)
        ).fetchall()
        return {row["bvid"] for row in rows}


def find_sub_by_uid(identity: dict, uid: str, platform: str = "bilibili") -> dict | None:
    owner_sql, owner_params = _owner_clause(identity)
    with get_db() as conn:
        row = conn.execute(
            "SELECT s.id FROM blogger_subs s JOIN blogger_creators c ON c.id = s.creator_id "
            f"WHERE c.platform = ? AND c.uid = ? AND s.{owner_sql}",
            [platform, uid, *owner_params],
        ).fetchone()
        return _row_to_dict(row)


def list_videos(creator_id: int, *, q: str = "", offset: int = 0, limit: int = 30,
                extra_where: str | None = None, extra_params: list | None = None, anchor_id: int | None = None, locate_anchor: bool = False) -> dict:
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    where = ["v.creator_id = ?"]
    params: list = [creator_id]
    if q:
        where.append("(v.title LIKE ? OR v.description LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    if extra_where:
        where.append(extra_where)
        params.extend(extra_params or [])
    where_sql = " AND ".join(where)
    with get_db() as conn:
        from core.content_state import register_content_functions
        register_content_functions(conn)
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM blogger_videos v WHERE {where_sql}", params
        ).fetchone()["n"]
        anchor_index = None
        if anchor_id is not None:
            anchor = conn.execute(
                f"SELECT position FROM (SELECT v.id, ROW_NUMBER() OVER (ORDER BY v.published_at DESC, v.id DESC) - 1 AS position "
                f"FROM blogger_videos v WHERE {where_sql}) WHERE id = ?", [*params, anchor_id],
            ).fetchone()
            anchor_index = anchor[0] if anchor else None
        if locate_anchor and anchor_index is not None:
            offset = (anchor_index // limit) * limit
        if offset >= total:
            offset = max(0, ((total - 1) // limit) * limit)
        rows = conn.execute(
            f"SELECT v.* FROM blogger_videos v WHERE {where_sql} "
            "ORDER BY v.published_at DESC, v.id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        result = {"total": total, "items": [dict(row) for row in rows], "offset": offset, "limit": limit}
        if anchor_id is not None:
            result["anchor_index"] = anchor_index
        return result


def replace_pages(video_id: int, pages: list[dict]) -> None:
    now_rows = [
        (
            video_id,
            int(page.get("cid") or 0),
            int(page.get("page") or index + 1),
            page.get("part_title") or "",
            int(page.get("duration") or 0),
        )
        for index, page in enumerate(pages)
    ]
    with get_db() as conn:
        conn.execute("DELETE FROM blogger_video_pages WHERE video_id = ?", (video_id,))
        conn.executemany(
            "INSERT INTO blogger_video_pages (video_id, cid, page, part_title, duration) "
            "VALUES (?, ?, ?, ?, ?)",
            now_rows,
        )
        conn.execute(
            "UPDATE blogger_videos SET page_count = ? WHERE id = ?",
            (max(1, len(now_rows)), video_id),
        )


def list_pages(video_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM blogger_video_pages WHERE video_id = ? ORDER BY page",
            (video_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def has_pages(video_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM blogger_video_pages WHERE video_id = ?", (video_id,)
        ).fetchone()
        return row["n"] > 0


# ── syncs ──

def create_sync(creator_id: int, status: str = "queued") -> int:
    now = _now()
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO blogger_syncs (creator_id, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (creator_id, status, now, now),
        )
        return cursor.lastrowid


def update_sync(sync_id: int, **changes) -> bool:
    allowed = {
        "status", "page", "found", "expected", "error", "error_code",
        "retry_count", "started_at", "finished_at",
        "mode", "cancel_requested", "added",
    }
    fields = {key: value for key, value in changes.items() if key in allowed}
    if not fields:
        return False
    fields["updated_at"] = _now()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    with get_db() as conn:
        cursor = conn.execute(
            f"UPDATE blogger_syncs SET {assignments} WHERE id = ?",
            [*fields.values(), sync_id],
        )
        return cursor.rowcount > 0


def get_sync(sync_id: int) -> dict | None:
    with get_db() as conn:
        return _row_to_dict(conn.execute(
            "SELECT * FROM blogger_syncs WHERE id = ?", (sync_id,)
        ).fetchone())


def latest_sync(creator_id: int) -> dict | None:
    with get_db() as conn:
        return _row_to_dict(conn.execute(
            "SELECT * FROM blogger_syncs WHERE creator_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (creator_id,),
        ).fetchone())


def has_full_catalog_sync(creator_id: int) -> bool:
    """Only a scan that reached the reported total establishes a complete baseline."""
    with get_db() as conn:
        return conn.execute(
            "SELECT 1 FROM blogger_syncs WHERE creator_id = ? AND status = 'complete' "
            "AND expected > 0 AND found >= expected LIMIT 1", (creator_id,),
        ).fetchone() is not None


def sync_running(creator_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM blogger_syncs WHERE creator_id = ? AND status = 'running'",
            (creator_id,),
        ).fetchone()
        return row["n"] > 0


def active_sync(creator_id: int) -> dict | None:
    """最新 queued/running 的同步行（含重试等待中的 queued）。"""
    with get_db() as conn:
        return _row_to_dict(conn.execute(
            "SELECT * FROM blogger_syncs WHERE creator_id = ? "
            "AND status IN ('queued', 'running') ORDER BY created_at DESC, id DESC LIMIT 1",
            (creator_id,),
        ).fetchone())


def cancel_sync(creator_id: int) -> dict:
    """取消活跃同步：queued 直接终止，running 置 cancel_requested 由执行线程收敛。"""
    sync = active_sync(creator_id)
    if not sync:
        return {"cancelled": False, "sync": None}
    if sync["status"] == "queued":
        update_sync(sync["id"], status="cancelled", cancel_requested=1, finished_at=now_iso())
    else:
        update_sync(sync["id"], cancel_requested=1)
    return {"cancelled": True, "sync": get_sync(sync["id"])}


def is_sync_cancelled(sync_id: int) -> bool:
    sync = get_sync(sync_id)
    return bool(sync) and (
        bool(sync.get("cancel_requested")) or sync.get("status") == "cancelled"
    )


def preview_remove(sub_id: int, identity: dict) -> dict | None:
    """删除预览：统计将清理的内容，并明确学习资料保留。"""
    sub = get_sub(sub_id, identity)
    if not sub:
        return None
    creator_id = sub["creator_id"]
    with get_db() as conn:
        videos = conn.execute(
            "SELECT COUNT(*) AS n FROM blogger_videos WHERE creator_id = ?", (creator_id,)
        ).fetchone()["n"]
        pages = conn.execute(
            "SELECT COUNT(*) AS n FROM blogger_video_pages WHERE video_id IN "
            "(SELECT id FROM blogger_videos WHERE creator_id = ?)", (creator_id,)
        ).fetchone()["n"]
        batches = conn.execute(
            "SELECT COUNT(*) AS n FROM blogger_batches WHERE creator_id = ?", (creator_id,)
        ).fetchone()["n"]
        syncs = conn.execute(
            "SELECT COUNT(*) AS n FROM blogger_syncs WHERE creator_id = ?", (creator_id,)
        ).fetchone()["n"]
        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM blogger_subs WHERE creator_id = ? AND id != ?",
            (creator_id, sub_id),
        ).fetchone()["n"]
        active_sync_n = conn.execute(
            "SELECT COUNT(*) AS n FROM blogger_syncs WHERE creator_id = ? "
            "AND status IN ('queued', 'running')", (creator_id,)
        ).fetchone()["n"]
        active_batch_n = conn.execute(
            "SELECT COUNT(*) AS n FROM blogger_batches WHERE creator_id = ? "
            "AND status IN ('queued', 'running')", (creator_id,)
        ).fetchone()["n"]
    return {
        "sub": sub,
        "will_remove": {
            "subscription": 1,
            "videos": videos,
            "pages": pages,
            "batches": batches,
            "syncs": syncs,
        },
        "cascade": remaining == 0 and active_sync_n == 0 and active_batch_n == 0,
        "remaining_subscribers": remaining,
        "blocked_by_active": {"sync": active_sync_n > 0, "batch": active_batch_n > 0},
        "preserved": {
            "ai_cache": True,
            "subtitles": True,
            "user_history": True,
            "note": "摘要/笔记/思维导图/问答、字幕、学习历史全部保留；重新订阅后批量生成自动复用缓存，不重复解析",
        },
    }


def recover_stale_syncs() -> int:
    """启动恢复：running 一律置 interrupted，保留 page 游标供续跑。"""
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE blogger_syncs SET status = 'interrupted', updated_at = ? "
            "WHERE status IN ('queued', 'running')",
            (_now(),),
        )
        return cursor.rowcount
