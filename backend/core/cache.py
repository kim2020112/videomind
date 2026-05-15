"""AI 结果 SQLite 持久化缓存 — 同 URL 不重复消耗 AI token。"""

import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from config import DB_PATH


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _ensure_table():
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_cache (
                url_hash TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                video_title TEXT DEFAULT '',
                subtitle_text TEXT DEFAULT '',
                source TEXT DEFAULT '',
                result_json TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_cache_url_hash ON ai_cache(url_hash)
        """)


_ensure_table()


def get_cached(url: str) -> dict | None:
    """获取缓存的 AI 结果。返回 None 表示未命中。"""
    h = _url_hash(url)
    tz = timezone(timedelta(hours=8))
    with sqlite3.connect(str(DB_PATH)) as conn:
        row = conn.execute(
            "SELECT url, video_title, subtitle_text, source, result_json, created_at, updated_at FROM ai_cache WHERE url_hash = ?",
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
        "created_at": row[5],
        "updated_at": row[6],
    }


def save_cache(url: str, video_title: str = "", subtitle_text: str = "", source: str = "", result_json: str = ""):
    """保存或更新 AI 结果缓存。"""
    h = _url_hash(url)
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).isoformat()
    with sqlite3.connect(str(DB_PATH)) as conn:
        existing = conn.execute("SELECT url_hash FROM ai_cache WHERE url_hash = ?", (h,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE ai_cache SET video_title=?, subtitle_text=?, source=?, result_json=?, updated_at=? WHERE url_hash=?",
                (video_title, subtitle_text, source, result_json, now, h),
            )
        else:
            conn.execute(
                "INSERT INTO ai_cache (url_hash, url, video_title, subtitle_text, source, result_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (h, url, video_title, subtitle_text, source, result_json, now, now),
            )


def list_history(limit: int = 20) -> list[dict]:
    """列出历史学习记录。"""
    with sqlite3.connect(str(DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT url, video_title, source, result_json, created_at FROM ai_cache ORDER BY updated_at DESC LIMIT ?",
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
            "created_at": row[4],
        })
    return results


def delete_cache(url: str):
    """删除指定 URL 的缓存。"""
    h = _url_hash(url)
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute("DELETE FROM ai_cache WHERE url_hash = ?", (h,))


# ──── Whisper 转录缓存 ────

def _ensure_whisper_table():
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS whisper_cache (
                url_hash TEXT PRIMARY KEY,
                url TEXT NOT NULL,
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


_ensure_whisper_table()


def get_whisper_cache(url: str) -> str | None:
    """获取缓存的 Whisper 转录文本（校正后）。返回 None 表示未命中。"""
    h = _url_hash(url)
    with sqlite3.connect(str(DB_PATH)) as conn:
        row = conn.execute(
            "SELECT subtitle_text FROM whisper_cache WHERE url_hash = ?",
            (h,),
        ).fetchone()
    if not row:
        return None
    return row[0]


def save_whisper_cache(url: str, subtitle_text: str, language: str = "", raw_text: str = ""):
    """保存 Whisper 转录文本。subtitle_text 为校正后（或原始）文本，raw_text 为原始转录。"""
    h = _url_hash(url)
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).isoformat()
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO whisper_cache (url_hash, url, subtitle_text, language, raw_text, created_at) VALUES (?,?,?,?,?,?)",
            (h, url, subtitle_text, language, raw_text, now),
        )


# ──── 视频信息缓存（避免重复 yt-dlp 解析） ────

def _ensure_video_info_table():
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS video_info_cache (
                url_hash TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                duration REAL DEFAULT 0,
                title TEXT DEFAULT '',
                info_json TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)


_ensure_video_info_table()


def get_video_info_cache(url: str) -> dict | None:
    """获取缓存的视频基本信息。返回 None 表示未命中。"""
    h = _url_hash(url)
    with sqlite3.connect(str(DB_PATH)) as conn:
        row = conn.execute(
            "SELECT duration, title, info_json FROM video_info_cache WHERE url_hash = ?",
            (h,),
        ).fetchone()
    if not row:
        return None
    info = json.loads(row[2]) if row[2] else {}
    info["duration"] = row[0]
    info["title"] = row[1]
    return info


def save_video_info_cache(url: str, info):
    """保存视频基本信息到缓存。info 为 VideoInfo 对象或 dict。"""
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

    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO video_info_cache (url_hash, url, duration, title, info_json, created_at) VALUES (?,?,?,?,?,?)",
            (h, url, duration, title, json.dumps(info_dict, ensure_ascii=False), now),
        )
