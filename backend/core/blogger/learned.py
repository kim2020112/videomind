"""Identity-scoped badges, filters and statistics, independent of job state."""
from core.cache import _ensure_table, _extract_part_index, _extract_video_key
from core.content_state import content_state, register_content_functions
from database import get_db


def _identity_clause(identity):
    user = None
    if identity.get("user_id"):
        from core.auth import get_user_by_id
        user = get_user_by_id(identity["user_id"])
    if ((user or {}).get("role") or identity.get("role")) == "admin":
        return "1 = 1", []
    if identity.get("user_id") is not None:
        return "uh.user_id = ?", [identity["user_id"]]
    if identity.get("guest_id"):
        return "uh.guest_id = ?", [identity["guest_id"]]
    return "1 = 0", []


SUBTITLE_TEXT_SQL = """COALESCE((SELECT s.full_text FROM subtitles s JOIN videos sv ON sv.id=s.video_id
    WHERE sv.url=uh.url AND TRIM(s.full_text) != '' LIMIT 1),
    CASE WHEN COALESCE(ac.source,'') != 'description' THEN ac.subtitle_text END, '')"""

SUBTITLE_SQL = """(
    EXISTS (SELECT 1 FROM subtitles s JOIN videos sv ON sv.id = s.video_id
            WHERE sv.url = uh.url AND TRIM(s.full_text) != '')
    OR (TRIM(COALESCE(ac.subtitle_text, '')) != '' AND COALESCE(ac.source, '') != 'description')
)"""


def _exists_sql(identity, condition):
    owner, params = _identity_clause(identity)
    return ("EXISTS (SELECT 1 FROM user_history uh LEFT JOIN ai_cache ac ON ac.url_hash=uh.url_hash "
            f"WHERE {owner} AND vm_video_key(uh.url) = 'bilibili:' || v.bvid AND {condition})", params)


def learned_exists_sql(identity, learned="all"):
    if learned not in ("learned", "unlearned"):
        return None, []
    _ensure_table()
    sql, params = _exists_sql(identity, "vm_module_count(ac.result_json) > 0")
    return (f"NOT {sql}" if learned == "unlearned" else sql), params


def subtitle_exists_sql(identity):
    _ensure_table()
    return _exists_sql(identity, SUBTITLE_SQL)


def content_by_bvid(identity, bvids):
    """Batch requested videos; filter by owner in SQL before decoding results."""
    _ensure_table()
    owner, params = _identity_clause(identity)
    wanted = list(set(bvids))
    result = {}
    with get_db() as conn:
        register_content_functions(conn)
        for start in range(0, len(wanted), 200):
            batch = wanted[start:start + 200]
            placeholders = ','.join('?' for _ in batch)
            rows = conn.execute(
                f"SELECT uh.url, ac.result_json, {SUBTITLE_SQL} AS has_subtitle, {SUBTITLE_TEXT_SQL} AS subtitle_text FROM user_history uh "
                "LEFT JOIN ai_cache ac ON ac.url_hash=uh.url_hash "
                f"WHERE {owner} AND vm_video_key(uh.url) IN ({placeholders})",
                [*params, *(f"bilibili:{bvid}" for bvid in batch)],
            ).fetchall()
            for row in rows:
                bvid = _extract_video_key(row["url"]).split(":", 1)[1]
                page = _extract_part_index(row["url"])
                state = content_state(row["result_json"], row["has_subtitle"], row["subtitle_text"])
                previous = result.setdefault(bvid, {}).get(page)
                if previous:
                    modules = [m for m in ("summary", "mindmap", "notes", "qa") if m in set(previous["modules"]) | set(state["modules"])]
                    state["modules"], state["module_count"] = modules, len(modules)
                    state["stale_modules"] = list(set(state["stale_modules"]) | set(previous["stale_modules"]))
                    state["has_subtitle"] |= previous["has_subtitle"]
                    state["has_description_summary"] |= previous["has_description_summary"]
                    state["coverage"] = "complete" if len(modules) == 4 else "partial" if modules else "subtitle" if state["has_subtitle"] else "empty"
                result[bvid][page] = state
    return result


def learned_bvid_sets(identity):
    """Compatibility helper for older internal callers."""
    with get_db() as conn:
        bvids = [r[0] for r in conn.execute("SELECT bvid FROM blogger_videos")]
    return {bvid: {p for p, state in parts.items() if state["module_count"]} for bvid, parts in content_by_bvid(identity, bvids).items()}


def video_counts(identity, creator_ids):
    if not creator_ids:
        return {}
    _ensure_table()
    organized, organized_params = _exists_sql(identity, "vm_module_count(ac.result_json) > 0")
    subtitle, subtitle_params = subtitle_exists_sql(identity)
    placeholders = ','.join('?' for _ in creator_ids)
    with get_db() as conn:
        register_content_functions(conn)
        rows = conn.execute(
            f"SELECT v.creator_id, SUM({organized}) AS organized_count, SUM({subtitle}) AS subtitle_count "
            f"FROM blogger_videos v WHERE v.creator_id IN ({placeholders}) GROUP BY v.creator_id",
            [*organized_params, *subtitle_params, *creator_ids],
        ).fetchall()
    return {r["creator_id"]: {"organized_count": r["organized_count"], "subtitle_count": r["subtitle_count"]} for r in rows}


def learned_video_counts(identity, creator_ids):
    return {key: value["organized_count"] for key, value in video_counts(identity, creator_ids).items()}
