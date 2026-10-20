"""已学习/已生成内容判定。

语义与 core/cache.get_learned_part_indexes 一致：
当前身份 user_history.status='done'（admin 不限身份）且 ai_cache.result_json 非空。
SQL 过滤与 Python 分 P 标记共用本模块条件，保证列表筛选与徽章一致。
"""

from __future__ import annotations

from core.cache import _ensure_table as _ensure_ai_cache_table, _extract_part_index, _extract_video_key
from database import get_db


def _ready() -> None:
    _ensure_ai_cache_table()  # ai_cache 为懒建表


def _identity_clause(identity: dict) -> tuple[list[str], list]:
    """返回作用在 (user_history uh JOIN ai_cache ac ON ac.url_hash=uh.url_hash) 上的条件。"""
    conditions = [
        "COALESCE(uh.status, 'done') = 'done'",
        "ac.result_json IS NOT NULL AND TRIM(ac.result_json) != ''",
    ]
    params: list = []
    user = None
    if identity.get("user_id"):
        from core.auth import get_user_by_id
        user = get_user_by_id(identity["user_id"])
    role = (user or {}).get("role") or identity.get("role") or "guest"
    if role != "admin":
        if identity.get("user_id"):
            conditions.append("uh.user_id = ?")
            params.append(identity["user_id"])
        elif identity.get("guest_id"):
            conditions.append("uh.guest_id = ?")
            params.append(identity["guest_id"])
        else:
            conditions.append("1 = 0")
    return conditions, params


def learned_bvid_sets(identity: dict) -> dict[str, set[int]]:
    """bvid → 已学分 P 序号集合（全量，调用方按需取用）。"""
    _ready()
    conditions, params = _identity_clause(identity)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT uh.url FROM user_history uh "
            "JOIN ai_cache ac ON ac.url_hash = uh.url_hash "
            f"WHERE {' AND '.join(conditions)}",
            params,
        ).fetchall()
    result: dict[str, set[int]] = {}
    for row in rows:
        key = _extract_video_key(row["url"])
        if not key.startswith("bilibili:"):
            continue
        result.setdefault(key.split(":", 1)[1], set()).add(_extract_part_index(row["url"]))
    return result


def learned_video_counts(identity: dict, creator_ids: list[int]) -> dict[int, int]:
    """creator_id → 已学视频数（bvid 级去重）。"""
    if not creator_ids:
        return {}
    _ready()
    conditions, params = _identity_clause(identity)
    placeholders = ",".join("?" for _ in creator_ids)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT v.creator_id AS creator_id, COUNT(DISTINCT v.bvid) AS n "
            "FROM blogger_videos v "
            "WHERE v.creator_id IN (" + placeholders + ") AND EXISTS ("
            "SELECT 1 FROM user_history uh "
            "JOIN ai_cache ac ON ac.url_hash = uh.url_hash "
            f"WHERE INSTR(uh.url, v.bvid) > 0 AND {' AND '.join(conditions)}"
            ") GROUP BY v.creator_id",
            [*creator_ids, *params],
        ).fetchall()
    return {row["creator_id"]: row["n"] for row in rows}


def learned_exists_sql(identity: dict, learned: str = "all") -> tuple[str | None, list]:
    """供 store.list_videos 的 extra_where 用的 EXISTS 过滤片段。

    learned: 'all' | 'learned' | 'unlearned'
    """
    if learned not in ("learned", "unlearned"):
        return None, []
    _ready()
    conditions, params = _identity_clause(identity)
    exists = (
        "EXISTS (SELECT 1 FROM user_history uh "
        "JOIN ai_cache ac ON ac.url_hash = uh.url_hash "
        f"WHERE INSTR(uh.url, v.bvid) > 0 AND {' AND '.join(conditions)})"
    )
    if learned == "unlearned":
        return f"NOT {exists}", params
    return exists, params
