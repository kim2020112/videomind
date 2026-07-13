"""AI 结果 SQLite 持久化缓存 — 基于视频指纹避免重复消耗 AI token。"""

import hashlib
import json
import re
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from config import DB_PATH
from database import get_db as _get_db
from core.logging_config import get_logger

logger = get_logger(__name__)


def _conn():
    """使用统一的数据库连接管理（委托给 database.get_db）。"""
    return _get_db()

_initialized = False


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _is_multipart_url(url: str) -> bool:
    return bool(re.search(r"[?&]p=\d+", url or ""))


def video_fingerprint(extractor: str, video_id: str) -> str:
    """构建视频分组指纹；分 P 的缓存身份始终使用精确 URL hash。"""
    import re as _re
    video_id = _re.sub(r'_p\d+$', '', video_id)
    return f"{extractor}:{video_id}"


# ──── AI 缓存 ────

def _ensure_table():
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_cache (
                url_hash TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                fingerprint TEXT DEFAULT '',
                video_title TEXT DEFAULT '',
                subtitle_text TEXT DEFAULT '',
                source TEXT DEFAULT '',
                result_json TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # 迁移旧表：先加列，再建索引
        try:
            conn.execute("ALTER TABLE ai_cache ADD COLUMN fingerprint TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE ai_cache ADD COLUMN part_info TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE ai_cache ADD COLUMN is_favorite INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE ai_cache ADD COLUMN platform TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE ai_cache ADD COLUMN notes_chars INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE ai_cache ADD COLUMN prompt_version INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        # 回填已有记录的 notes_chars（只处理 notes_chars=0 的记录）
        rows = conn.execute("SELECT url_hash, result_json FROM ai_cache WHERE notes_chars = 0 AND result_json != ''").fetchall()
        for row in rows:
            nc = _compute_notes_chars(row[1])
            if nc > 0:
                conn.execute("UPDATE ai_cache SET notes_chars = ? WHERE url_hash = ?", (nc, row[0]))
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_cache_url_hash ON ai_cache(url_hash)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_cache_fingerprint ON ai_cache(fingerprint)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_cache_created_at ON ai_cache(created_at)
        """)


def init_cache():
    """应用启动时一次性初始化所有缓存表。"""
    global _initialized
    if _initialized:
        return
    _ensure_table()
    _ensure_whisper_table()
    _ensure_video_info_table()
    _initialized = True


def _max_prompt_version() -> int:
    """取所有模块 prompt 版本的最大值，作为缓存版本号。"""
    from config import SUMMARY_PROMPT_VERSION, NOTES_PROMPT_VERSION, MINDMAP_PROMPT_VERSION, QANDA_PROMPT_VERSION
    return max(SUMMARY_PROMPT_VERSION, NOTES_PROMPT_VERSION, MINDMAP_PROMPT_VERSION, QANDA_PROMPT_VERSION)


def get_cached(url: str, fingerprint: str = None) -> dict | None:
    """获取 AI 缓存；精确 URL 优先，指纹只兼容非分 P 链接。"""
    current_version = _max_prompt_version()
    h = _url_hash(url)
    with _conn() as conn:
        row = conn.execute(
            "SELECT url, video_title, subtitle_text, source, result_json, part_info, created_at, updated_at, prompt_version, platform FROM ai_cache WHERE url_hash = ?",
            (h,),
        ).fetchone()
        if not row and fingerprint and not _is_multipart_url(url):
            candidates = conn.execute(
                "SELECT url, video_title, subtitle_text, source, result_json, part_info, created_at, updated_at, prompt_version, platform "
                "FROM ai_cache WHERE fingerprint = ? ORDER BY updated_at DESC",
                (fingerprint,),
            ).fetchall()
            row = next((candidate for candidate in candidates if not _is_multipart_url(candidate[0])), None)
    if not row:
        return None
    # prompt 版本不匹配视为 miss（但保留数据供部分重新生成用）
    cached_version = row[8] if len(row) > 8 else 0
    if cached_version != current_version:
        logger.info(f"prompt_version 不匹配: cached={cached_version} current={current_version}，视为 miss")
        return None
    return {
        "url": row[0],
        "video_title": row[1],
        "subtitle_text": row[2],
        "source": row[3],
        "result_json": row[4],
        "part_info": row[5] or "",
        "created_at": row[6],
        "updated_at": row[7],
        "platform": row[9] or "",
    }


def _get_cached_raw(url: str) -> dict | None:
    """读取缓存行（跳过 prompt_version 检查，供 Q&A 合并写入用）。"""
    h = _url_hash(url)
    with _conn() as conn:
        row = conn.execute(
            "SELECT url, video_title, subtitle_text, source, result_json, part_info, fingerprint, platform FROM ai_cache WHERE url_hash = ?",
            (h,),
        ).fetchone()
    if not row:
        return None
    return {
        "url": row[0],
        "video_title": row[1],
        "subtitle_text": row[2],
        "source": row[3],
        "result_json": row[4],
        "part_info": row[5] or "",
        "fingerprint": row[6] or "",
        "platform": row[7] or "",
    }


def _compute_notes_chars(result_json: str) -> int:
    """从 result_json 中提取 notes 字段并计算字数。"""
    if not result_json:
        return 0
    try:
        data = json.loads(result_json)
        notes = data.get("notes", "")
        if not notes:
            inner = data.get("result", {})
            if isinstance(inner, dict):
                notes = inner.get("notes", "")
        return len(notes)
    except (json.JSONDecodeError, TypeError):
        return 0


def _cleanup_old_cache(conn):
    """保留最新的 50 个视频的缓存，删除超出的旧记录。
    按 fingerprint（视频唯一标识，如 bilibili:BVxxx）去重计数：
    - 一个多P视频（如 185P）算 1 个视频，所有分P都保留
    - 无 fingerprint 的记录按单条计数，保留最新的 50 条
    """
    # 1. 收集需删除的 URL（在删除前收集，用于级联清理）
    old_urls = []
    # 有 fingerprint: 找出不在 top 50 的视频
    kept_fps = conn.execute(
        "SELECT DISTINCT fingerprint FROM ai_cache WHERE fingerprint != '' ORDER BY updated_at DESC LIMIT 50"
    ).fetchall()
    if kept_fps:
        placeholders = ','.join('?' for _ in kept_fps)
        old = conn.execute(
            f"SELECT url FROM ai_cache WHERE fingerprint != '' AND fingerprint NOT IN ({placeholders})",
            [r[0] for r in kept_fps],
        ).fetchall()
        old_urls.extend(old)
        conn.execute(
            f"DELETE FROM ai_cache WHERE fingerprint != '' AND fingerprint NOT IN ({placeholders})",
            [r[0] for r in kept_fps],
        )
    # 无 fingerprint: 保留最新的 50 条
    old = conn.execute(
        "SELECT url FROM ai_cache WHERE (fingerprint = '' OR fingerprint IS NULL) "
        "AND url_hash NOT IN ("
        "SELECT url_hash FROM ai_cache WHERE fingerprint = '' OR fingerprint IS NULL ORDER BY updated_at DESC LIMIT 50"
        ")"
    ).fetchall()
    old_urls.extend(old)
    conn.execute(
        "DELETE FROM ai_cache WHERE (fingerprint = '' OR fingerprint IS NULL) AND url_hash NOT IN ("
        "SELECT url_hash FROM ai_cache WHERE fingerprint = '' OR fingerprint IS NULL ORDER BY updated_at DESC LIMIT 50"
        ")"
    )
    # 级联清理 knowledge.db 中不再被缓存引用的关联数据
    if old_urls:
        try:
            with _get_db() as kconn:
                for (url,) in old_urls:
                    video = kconn.execute("SELECT id FROM videos WHERE url = ?", (url,)).fetchone()
                    if video:
                        kconn.execute("DELETE FROM video_tags WHERE video_id = ?", (video["id"],))
                        kconn.execute("DELETE FROM subtitles WHERE video_id = ?", (video["id"],))
                        kconn.execute("DELETE FROM videos WHERE id = ?", (video["id"],))
                kconn.execute("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM video_tags)")
        except Exception:
            pass


def save_cache(url: str, video_title: str = "", subtitle_text: str = "", source: str = "", result_json: str = "", fingerprint: str = None, part_info: str = "", platform: str = "", prompt_version: int = 0):
    """按精确 URL hash 保存或更新 AI 结果缓存。"""
    h = _url_hash(url)
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).isoformat()
    nc = _compute_notes_chars(result_json)
    with _conn() as conn:
        # 指纹只用于分组；同一分 P 是否已存在由 URL hash 判断。
        if fingerprint:
            existing = conn.execute("SELECT url_hash FROM ai_cache WHERE url_hash = ?", (h,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE ai_cache SET url=?, video_title=?, subtitle_text=?, source=?, result_json=?, updated_at=?, part_info=?, platform=?, notes_chars=?, prompt_version=?, fingerprint=COALESCE(NULLIF(?, ''), fingerprint) WHERE url_hash=?",
                    (url, video_title, subtitle_text, source, result_json, now, part_info, platform, nc, prompt_version, fingerprint or '', h),
                )
                _cleanup_old_cache(conn)
                return
        # 无指纹或指纹未命中：按 url_hash 更新或插入（INSERT OR REPLACE 防止并发 UNIQUE 冲突）
        conn.execute(
            "INSERT OR REPLACE INTO ai_cache (url_hash, url, fingerprint, video_title, subtitle_text, source, result_json, part_info, platform, notes_chars, prompt_version, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (h, url, fingerprint or '', video_title, subtitle_text, source, result_json, part_info, platform, nc, prompt_version, now, now),
        )
        _cleanup_old_cache(conn)


def list_history(limit: int = 20) -> list[dict]:
    """列出历史学习记录。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT url, video_title, source, result_json, part_info, created_at FROM ai_cache ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    results = []
    for row in rows:
        try:
            result = json.loads(row[3]) if row[3] else {}
        except json.JSONDecodeError:
            result = {}
        results.append({
            "url": row[0],
            "video_title": row[1] or result.get("title", ""),
            "source": row[2],
            "summary": result.get("summary", ""),
            "notes": result.get("notes", ""),
            "flashcards": result.get("flashcards", []),
            "part_info": row[4] or "",
            "created_at": row[5],
        })
    return results


def delete_cache(url: str, fingerprint: str = None):
    """按精确 URL hash 删除 AI 缓存，同时级联清理关联数据。"""
    h = _url_hash(url)
    # 清理 knowledge.db 中的关联数据（视频、字幕、标签）
    try:
        with _get_db() as conn:
            video = conn.execute("SELECT id FROM videos WHERE url = ?", (url,)).fetchone()
            if video:
                conn.execute("DELETE FROM video_tags WHERE video_id = ?", (video["id"],))
                conn.execute("DELETE FROM subtitles WHERE video_id = ?", (video["id"],))
                conn.execute("DELETE FROM videos WHERE id = ?", (video["id"],))
                conn.execute("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM video_tags)")
    except Exception:
        pass
    with _conn() as conn:
        conn.execute("DELETE FROM ai_cache WHERE url_hash = ?", (h,))


def delete_whisper_cache(url: str, fingerprint: str = None):
    """按精确 URL hash 删除 Whisper 缓存。"""
    h = _url_hash(url)
    with _conn() as conn:
        conn.execute("DELETE FROM whisper_cache WHERE url_hash = ?", (h,))


# ──── Whisper 转录缓存 ────

def _ensure_whisper_table():
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS whisper_cache (
                url_hash TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                fingerprint TEXT DEFAULT '',
                subtitle_text TEXT NOT NULL,
                language TEXT DEFAULT '',
                raw_text TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        try:
            conn.execute("ALTER TABLE whisper_cache ADD COLUMN raw_text TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE whisper_cache ADD COLUMN fingerprint TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass


def get_whisper_cache(url: str, fingerprint: str = None) -> str | None:
    """获取 Whisper 转录；精确 URL 优先，指纹只兼容非分 P 链接。"""
    h = _url_hash(url)
    with _conn() as conn:
        row = conn.execute(
            "SELECT subtitle_text FROM whisper_cache WHERE url_hash = ?",
            (h,),
        ).fetchone()
        if row:
            return row[0]
        if fingerprint and not _is_multipart_url(url):
            candidates = conn.execute(
                "SELECT url, subtitle_text FROM whisper_cache WHERE fingerprint = ? ORDER BY created_at DESC",
                (fingerprint,),
            ).fetchall()
            row = next((candidate for candidate in candidates if not _is_multipart_url(candidate[0])), None)
    return row[1] if row else None


def save_whisper_cache(url: str, subtitle_text: str, language: str = "", raw_text: str = "", fingerprint: str = None):
    """按精确 URL hash 保存 Whisper 转录文本。"""
    h = _url_hash(url)
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).isoformat()
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO whisper_cache (url_hash, url, fingerprint, subtitle_text, language, raw_text, created_at) VALUES (?,?,?,?,?,?,?)",
            (h, url, fingerprint or '', subtitle_text, language, raw_text, now),
        )


# ──── 视频信息缓存（避免重复 yt-dlp 解析） ────

def _ensure_video_info_table():
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS video_info_cache (
                url_hash TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                fingerprint TEXT DEFAULT '',
                duration REAL DEFAULT 0,
                title TEXT DEFAULT '',
                info_json TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        try:
            conn.execute("ALTER TABLE video_info_cache ADD COLUMN fingerprint TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass


def get_video_info_cache(url: str, fingerprint: str = None) -> dict | None:
    """获取视频信息；精确 URL 优先，指纹只兼容非分 P 链接。"""
    h = _url_hash(url)
    with _conn() as conn:
        row = conn.execute(
            "SELECT duration, title, info_json FROM video_info_cache WHERE url_hash = ?",
            (h,),
        ).fetchone()
        if not row and fingerprint and not _is_multipart_url(url):
            candidates = conn.execute(
                "SELECT url, duration, title, info_json FROM video_info_cache "
                "WHERE fingerprint = ? ORDER BY created_at DESC",
                (fingerprint,),
            ).fetchall()
            candidate = next(
                (item for item in candidates if not _is_multipart_url(item[0])),
                None,
            )
            if candidate:
                row = (candidate[1], candidate[2], candidate[3])
    if not row:
        return None
    info = json.loads(row[2]) if row[2] else {}
    info["duration"] = row[0]
    info["title"] = row[1]
    return info


def save_video_info_cache(url: str, info, fingerprint: str = None):
    """保存视频基本信息到缓存。"""
    h = _url_hash(url)
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).isoformat()

    if hasattr(info, "model_dump"):
        info_dict = info.model_dump()
    elif hasattr(info, "dict"):
        info_dict = info.dict()
    else:
        info_dict = dict(info)

    duration = info_dict.get("duration") or 0
    title = info_dict.get("title") or ""

    with _conn() as conn:
        if fingerprint:
            existing = conn.execute(
                "SELECT url_hash FROM video_info_cache WHERE url_hash = ?",
                (h,),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE video_info_cache SET url=?, fingerprint=?, duration=?, title=?, info_json=?, created_at=? WHERE url_hash=?",
                    (url, fingerprint, duration, title, json.dumps(info_dict, ensure_ascii=False), now, h),
                )
                return
        conn.execute(
            "INSERT OR REPLACE INTO video_info_cache (url_hash, url, fingerprint, duration, title, info_json, created_at) VALUES (?,?,?,?,?,?,?)",
            (h, url, fingerprint or '', duration, title, json.dumps(info_dict, ensure_ascii=False), now),
        )


# ──── 标签读写（复用 database.py 的 tags/video_tags 表） ────

def save_tags(url: str, tags: list[str]):
    """将标签写入 tags + video_tags 表。通过 URL 匹配 videos 表获取 video_id。"""
    if not tags:
        return
    with _get_db() as conn:
        video = conn.execute("SELECT id FROM videos WHERE url = ?", (url,)).fetchone()
        if not video:
            return
        video_id = video["id"]
        for tag_name in tags:
            tag_name = tag_name.strip()
            if not tag_name:
                continue
            conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag_name,))
            tag_row = conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()
            if tag_row:
                conn.execute("INSERT OR IGNORE INTO video_tags (video_id, tag_id) VALUES (?, ?)", (video_id, tag_row["id"]))


def get_tags_for_url(url: str) -> list[str]:
    """获取 URL 对应的标签列表。"""
    with _get_db() as conn:
        rows = conn.execute("""
            SELECT t.name FROM tags t
            JOIN video_tags vt ON t.id = vt.tag_id
            JOIN videos v ON vt.video_id = v.id
            WHERE v.url = ?
            ORDER BY t.name
        """, (url,)).fetchall()
    return [r["name"] for r in rows]


def get_tags_for_urls(urls: list[str]) -> dict[str, list[str]]:
    """批量获取多个 URL 的标签，返回 {url: [tag_name, ...]}。"""
    if not urls:
        return {}
    result = {u: [] for u in urls}
    with _get_db() as conn:
        placeholders = ",".join("?" for _ in urls)
        rows = conn.execute(f"""
            SELECT v.url, t.name FROM tags t
            JOIN video_tags vt ON t.id = vt.tag_id
            JOIN videos v ON vt.video_id = v.id
            WHERE v.url IN ({placeholders})
            ORDER BY t.name
        """, urls).fetchall()
        for r in rows:
            u = r["url"]
            if u in result:
                result[u].append(r["name"])
    return result


def get_all_tags(user_id: int = None, guest_id: str = None, role: str = "guest") -> list[dict]:
    """获取标签及其使用次数。Admin 看全局，普通用户只看自己的。"""
    is_admin = (role == "admin")
    with _get_db() as conn:
        if is_admin:
            rows = conn.execute("""
                SELECT t.id, t.name, COUNT(vt.video_id) as count
                FROM tags t
                LEFT JOIN video_tags vt ON t.id = vt.tag_id
                GROUP BY t.id
                ORDER BY count DESC, t.name
            """).fetchall()
        elif user_id:
            rows = conn.execute("""
                SELECT t.id, t.name, COUNT(DISTINCT vt.video_id) as count
                FROM user_history uh
                JOIN ai_cache ac ON uh.url_hash = ac.url_hash
                JOIN videos v ON ac.url = v.url
                JOIN video_tags vt ON v.id = vt.video_id
                JOIN tags t ON vt.tag_id = t.id
                WHERE uh.user_id = ?
                GROUP BY t.id
                ORDER BY count DESC, t.name
            """, (user_id,)).fetchall()
        elif guest_id:
            rows = conn.execute("""
                SELECT t.id, t.name, COUNT(DISTINCT vt.video_id) as count
                FROM user_history uh
                JOIN ai_cache ac ON uh.url_hash = ac.url_hash
                JOIN videos v ON ac.url = v.url
                JOIN video_tags vt ON v.id = vt.video_id
                JOIN tags t ON vt.tag_id = t.id
                WHERE uh.guest_id = ?
                GROUP BY t.id
                ORDER BY count DESC, t.name
            """, (guest_id,)).fetchall()
        else:
            return []
    return [{"id": r["id"], "name": r["name"], "count": r["count"]} for r in rows]


# ──── 学习历史增强（搜索/过滤/收藏/多P合并） ────

def _extract_video_key(url: str) -> str:
    """提取视频唯一标识（用于多P合并）。B站用 BV 号，其他用完整 URL 去掉 ?p=N。"""
    bv = re.search(r'(BV\w+)', url)
    if bv:
        return f"bilibili:{bv.group(1)}"
    # 其他平台：去掉 ?p=N 参数
    return re.sub(r'[?&]p=\d+', '', url).rstrip('?&')


def _extract_part_index(url: str) -> int:
    """从 URL 提取分P序号，无分P返回 1（基础 URL 隐含 P1）。"""
    m = re.search(r'[?&]p=(\d+)', url)
    return int(m.group(1)) if m else 1


def get_learned_part_indexes(url: str, user_id: int = None, guest_id: str = None,
                             role: str = "guest") -> set[int]:
    """Return cached, completed multipart indexes visible to this identity."""
    conditions = [
        "COALESCE(uh.status, 'done') = 'done'",
        "ac.result_json IS NOT NULL",
        "TRIM(ac.result_json) != ''",
    ]
    params = []

    if role != "admin":
        if user_id is not None:
            conditions.append("uh.user_id = ?")
            params.append(user_id)
        elif guest_id:
            conditions.append("uh.guest_id = ?")
            params.append(guest_id)
        else:
            return set()

    with _get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT uh.url
            FROM user_history uh
            JOIN ai_cache ac ON ac.url_hash = uh.url_hash
            WHERE {' AND '.join(conditions)}
            """,
            params,
        ).fetchall()

    video_key = _extract_video_key(url)
    return {
        _extract_part_index(row["url"])
        for row in rows
        if _extract_video_key(row["url"]) == video_key
    }


def _get_cached_multipart_parts(conn, urls: list[str]) -> list[dict]:
    """返回同一 BV 任一 URL 中可用的完整分P元数据。"""
    for url in urls:
        row = conn.execute(
            "SELECT info_json FROM video_info_cache WHERE url_hash = ?",
            (_url_hash(url),),
        ).fetchone()
        if not row or not row[0]:
            continue
        try:
            parts = json.loads(row[0]).get("parts") or []
        except (json.JSONDecodeError, TypeError):
            continue
        if parts:
            return parts
    return []


def _get_total_parts_map(urls: list[str]) -> dict[str, int]:
    """批量查询多P视频的总分P数。返回 {url: total_parts}。"""
    # 按 BV 号分组，每组只需查一次 video_info_cache
    bv_urls: dict[str, list[str]] = {}
    for url in urls:
        bv = re.search(r'(BV\w+)', url)
        if bv:
            bv_urls.setdefault(bv.group(1), []).append(url)
    if not bv_urls:
        return {}
    result: dict[str, int] = {}
    with _get_db() as conn:
        for bv, group_urls in bv_urls.items():
            parts = _get_cached_multipart_parts(conn, group_urls)
            if parts:
                for u in group_urls:
                    result[u] = len(parts)
    return result


def _get_part_details_map(urls: list[str]) -> dict[str, dict[int, dict]]:
    """批量查询多P视频的分P详情。返回 {url: {part_index: {title, duration}}}。
    用于历史记录页面展示每P的标题和时长。"""
    bv_urls: dict[str, list[str]] = {}
    for url in urls:
        bv = re.search(r'(BV\w+)', url)
        if bv:
            bv_urls.setdefault(bv.group(1), []).append(url)
    if not bv_urls:
        return {}
    result: dict[str, dict[int, dict]] = {}
    with _get_db() as conn:
        for bv, group_urls in bv_urls.items():
            parts = _get_cached_multipart_parts(conn, group_urls)
            details: dict[int, dict] = {}
            for p in parts:
                idx = p.get("index")
                if idx is not None:
                    details[idx] = {
                        "title": p.get("title", ""),
                        "duration": p.get("duration") or 0,
                    }
            if details:
                for u in group_urls:
                    result[u] = details
    return result


def _get_summary_previews(url_hashes: list[str]) -> dict[str, str]:
    """批量获取摘要预览（仅提取 result_json 中的 summary 前 200 字符），避免加载完整 result_json。"""
    if not url_hashes:
        return {}
    result = {}
    with _get_db() as conn:
        # 分批查询，每批 50 个
        for i in range(0, len(url_hashes), 50):
            batch = url_hashes[i:i + 50]
            placeholders = ",".join("?" for _ in batch)
            rows = conn.execute(
                f"SELECT url_hash, result_json FROM ai_cache WHERE url_hash IN ({placeholders})",
                batch,
            ).fetchall()
            for row in rows:
                if not row["result_json"]:
                    result[row["url_hash"]] = ""
                    continue
                try:
                    data = json.loads(row["result_json"])
                    inner = data.get("result", {}) if isinstance(data.get("result"), dict) else {}
                    summary = inner.get("summary") or data.get("summary") or ""
                    result[row["url_hash"]] = summary[:200]
                except (json.JSONDecodeError, TypeError):
                    result[row["url_hash"]] = ""
    return result


def list_history_enhanced(q: str = None, tag: str = None, platform: str = None,
                          sort: str = "newest", limit: int = 50, offset: int = 0,
                          user_id: int = None, guest_id: str = None,
                          role: str = "guest") -> dict:
    """增强版历史列表：支持搜索、标签过滤、平台过滤，多P视频自动合并。按用户隔离。Admin 看全局。"""
    conditions = []
    params = []

    is_admin = (role == "admin")

    # 统一从 user_history 出发，LEFT JOIN ai_cache（admin 和普通用户都走这条路径）
    base = """
        FROM user_history uh
        LEFT JOIN ai_cache ac ON uh.url_hash = ac.url_hash
        LEFT JOIN videos v ON COALESCE(ac.url, uh.url) = v.url
        LEFT JOIN video_tags vt ON v.id = vt.video_id
        LEFT JOIN tags t ON vt.tag_id = t.id
    """
    if not is_admin:
        if user_id:
            conditions.append("uh.user_id = ?")
            params.append(user_id)
        elif guest_id:
            conditions.append("uh.guest_id = ?")
            params.append(guest_id)
        else:
            return {"total": 0, "items": []}

    if q:
        conditions.append("(ac.video_title LIKE ? OR ac.result_json LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like])

    if tag:
        conditions.append("t.name = ?")
        params.append(tag)

    if platform:
        conditions.append("(ac.platform = ? OR v.platform = ?)")
        params.extend([platform, platform])

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    order = "DESC" if sort == "newest" else "ASC"

    # 统一查询：从 user_history 出发，LEFT JOIN ai_cache
    # 用 CASE WHEN 处理空字符串（COALESCE 对 '' 不回退）
    with _get_db() as conn:
        rows = conn.execute(f"""
            SELECT DISTINCT uh.url_hash,
                   CASE WHEN ac.url IS NOT NULL AND ac.url != '' THEN ac.url ELSE uh.url END as url,
                   CASE WHEN ac.video_title IS NOT NULL AND ac.video_title != '' THEN ac.video_title ELSE uh.video_title END as video_title,
                   uh.created_at, uh.is_favorite, uh.status,
                   CASE WHEN ac.platform IS NOT NULL AND ac.platform != '' THEN ac.platform ELSE uh.platform END as platform,
                   ac.part_info,
                   v.platform as v_platform
            {base} {where}
            ORDER BY uh.created_at {order}
        """, params).fetchall()

    # 管理员的全局视图可能同时包含访客和登录用户对同一分P的记录；
    # 每个 url_hash 仅保留最新一条，避免在合并视频时重复显示同一分P。
    unique_rows = {}
    for row in rows:
        existing = unique_rows.get(row["url_hash"])
        if existing is None or row["created_at"] > existing["created_at"]:
            unique_rows[row["url_hash"]] = row
    rows = list(unique_rows.values())

    # 批量查询标签、分P信息
    all_urls = list(set(row["url"] for row in rows))
    tags_map = get_tags_for_urls(all_urls)
    total_parts_map = _get_total_parts_map(all_urls)
    part_details_map = _get_part_details_map(all_urls)

    # 按 video_key 分组
    groups = {}
    group_order = []
    for row in rows:
        key = _extract_video_key(row["url"])
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append(row)

    # 构建合并后的列表（不含 summary_preview，稍后批量加载）
    merged = []
    for key in group_order:
        parts_raw = groups[key]
        parts_raw.sort(key=lambda r: _extract_part_index(r["url"]))

        if len(parts_raw) == 1:
            row = parts_raw[0]
            item = _build_history_item(row, tags_map)
            item["is_multipart"] = False
            merged.append(item)
        else:
            first = parts_raw[0]
            parts_list = []
            latest_time = first["created_at"]
            any_favorite = False
            for row in parts_raw:
                part_index = _extract_part_index(row["url"])
                p_details = (part_details_map.get(row["url"], {})).get(part_index, {})
                parts_list.append({
                    "id": row["url_hash"],
                    "url": row["url"],
                    "part_index": part_index,
                    "part_info": row["part_info"] if "part_info" in row.keys() else "",
                    "part_title": p_details.get("title") or row["part_info"] or "",
                    "part_duration": p_details.get("duration") or 0,
                    "summary_preview": "",  # 稍后批量填充
                    "created_at": row["created_at"],
                })
                if row["created_at"] > latest_time:
                    latest_time = row["created_at"]
                if row["is_favorite"]:
                    any_favorite = True

            tags = tags_map.get(first["url"], [])
            platform_name = first["platform"] or ""
            total_parts = total_parts_map.get(first["url"], 0)
            # 取最高优先级状态: transcribing > generating > failed > done
            _status_order = {"transcribing": 0, "generating": 1, "failed": 2, "done": 3}
            part_statuses = [row["status"] if "status" in row.keys() and row["status"] else "done" for row in parts_raw]
            best_status = min(part_statuses, key=lambda s: _status_order.get(s, 99))

            merged.append({
                "id": key,
                "url": first["url"],
                "video_title": first["video_title"],
                "platform": platform_name,
                "tags": tags,
                "created_at": latest_time,
                "is_favorite": any_favorite,
                "status": best_status,
                "is_multipart": True,
                "parts_count": len(parts_list),
                "total_parts": total_parts,
                "parts": parts_list,
            })

    # 分页（基于合并后的列表）
    total = len(merged)
    page_items = merged[offset:offset + limit]

    # 第二步：仅为当前页的 item 批量加载摘要预览
    page_hashes = []
    for item in page_items:
        if item.get("is_multipart"):
            for p in item.get("parts", []):
                page_hashes.append(p["id"])
        else:
            page_hashes.append(item["id"])
    summaries = _get_summary_previews(page_hashes)

    for item in page_items:
        if item.get("is_multipart"):
            for p in item.get("parts", []):
                p["summary_preview"] = summaries.get(p["id"], "")[:100]
        else:
            item["summary_preview"] = summaries.get(item["id"], "")

    return {"total": total, "items": page_items}


def _build_history_item(row, tags_map: dict = None) -> dict:
    """从单行数据构建历史记录字典。不加载 result_json，summary_preview 由调用方批量填充。"""
    tags = tags_map.get(row["url"], []) if tags_map else get_tags_for_url(row["url"])
    return {
        "id": row["url_hash"],
        "url": row["url"],
        "url_hash": row["url_hash"],
        "video_title": row["video_title"] or "",
        "platform": row["platform"] or "",
        "summary_preview": "",  # 由 list_history_enhanced 批量填充
        "tags": tags,
        "created_at": row["created_at"],
        "is_favorite": bool(row["is_favorite"]),
        "status": row["status"] if "status" in row.keys() else "done",
    }


def toggle_favorite(url_hash: str, user_id: int = None, guest_id: str = None) -> bool:
    """切换收藏状态（基于 user_history），返回新状态。"""
    with _conn() as conn:
        if user_id:
            row = conn.execute(
                "SELECT is_favorite FROM user_history WHERE url_hash = ? AND user_id = ?",
                (url_hash, user_id),
            ).fetchone()
        elif guest_id:
            row = conn.execute(
                "SELECT is_favorite FROM user_history WHERE url_hash = ? AND guest_id = ?",
                (url_hash, guest_id),
            ).fetchone()
        else:
            return False
        if not row:
            return False
        new_val = 0 if row[0] else 1
        if user_id:
            conn.execute(
                "UPDATE user_history SET is_favorite = ? WHERE url_hash = ? AND user_id = ?",
                (new_val, url_hash, user_id),
            )
        else:
            conn.execute(
                "UPDATE user_history SET is_favorite = ? WHERE url_hash = ? AND guest_id = ?",
                (new_val, url_hash, guest_id),
            )
    return bool(new_val)


def get_learning_stats(user_id: int = None, guest_id: str = None, role: str = "guest") -> dict:
    """获取学习统计数据。按用户过滤。Admin 看全局，无身份返回空。"""
    tz = timezone(timedelta(hours=8))
    is_admin = (role == "admin")

    # 无身份：返回空统计
    if not is_admin and not user_id and not guest_id:
        return {
            "total_videos": 0,
            "total_notes_chars": 0,
            "avg_duration_seconds": 0,
            "platform_distribution": {},
            "recent_trend": [],
        }

    # 统一从 user_history 出发，LEFT JOIN ai_cache（和 list_history_enhanced 一致）
    user_filter = ""
    user_params = []
    if not is_admin:
        if user_id:
            user_filter = "WHERE uh.user_id = ?"
            user_params = [user_id]
        elif guest_id:
            user_filter = "WHERE uh.guest_id = ?"
            user_params = [guest_id]

    with _conn() as conn:
        total_videos = conn.execute(
            f"SELECT COUNT(*) FROM user_history uh {user_filter}", user_params
        ).fetchone()[0]

        total_notes_chars = conn.execute(f"""
            SELECT COALESCE(SUM(ac.notes_chars), 0)
            FROM user_history uh LEFT JOIN ai_cache ac ON uh.url_hash = ac.url_hash
            {user_filter}
        """, user_params).fetchone()[0]

        # 平均视频时长（去重：同一多P视频只算一次）
        def _video_key(url):
            bv = re.search(r'(BV\w+)', url)
            if bv:
                return bv.group(1)
            return url.split('?')[0].rstrip('/')

        urls_with_dur = conn.execute(f"""
            SELECT COALESCE(ac.url, uh.url) as url, MIN(vic.duration) as duration
            FROM user_history uh
            LEFT JOIN ai_cache ac ON uh.url_hash = ac.url_hash
            JOIN video_info_cache vic ON COALESCE(ac.url, uh.url) = vic.url
            {user_filter + (' AND' if user_filter else 'WHERE')} vic.duration > 0
            GROUP BY COALESCE(ac.url, uh.url)
        """, user_params).fetchall()

        seen = {}
        for row in urls_with_dur:
            key = _video_key(row[0])
            if key not in seen or row[1] < seen[key]:
                seen[key] = row[1]
        avg_duration = sum(seen.values()) / len(seen) if seen else 0

        # 平台分布（从 uh.platform 取，ai_cache 为空时也能正确显示）
        platform_rows = conn.execute(f"""
            SELECT CASE WHEN COALESCE(ac.platform, '') != '' THEN ac.platform
                        WHEN uh.platform != '' THEN uh.platform
                        WHEN v.platform IS NOT NULL THEN v.platform
                        ELSE 'unknown' END as p,
                   COUNT(DISTINCT uh.url_hash) as cnt
            FROM user_history uh
            LEFT JOIN ai_cache ac ON uh.url_hash = ac.url_hash
            LEFT JOIN videos v ON COALESCE(ac.url, uh.url) = v.url
            {user_filter}
            GROUP BY p
            ORDER BY cnt DESC
        """, user_params).fetchall()
        platform_distribution = {r[0]: r[1] for r in platform_rows}

        # 最近 7 天趋势
        seven_days_ago = (datetime.now(tz) - timedelta(days=7)).isoformat()
        trend_rows = conn.execute(f"""
            SELECT DATE(uh.created_at) as date, COUNT(*) as count
            FROM user_history uh
            {user_filter + (' AND' if user_filter else 'WHERE')} uh.created_at >= ?
            GROUP BY DATE(uh.created_at)
            ORDER BY date
        """, user_params + [seven_days_ago]).fetchall()
        recent_trend = [{"date": r[0], "count": r[1]} for r in trend_rows]

    return {
        "total_videos": total_videos,
        "total_notes_chars": total_notes_chars,
        "avg_duration_seconds": int(avg_duration),
        "platform_distribution": platform_distribution,
        "recent_trend": recent_trend,
    }
