import sqlite3
from contextlib import contextmanager
from config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    platform TEXT,
    uploader TEXT,
    duration INTEGER,
    thumbnail_url TEXT,
    description TEXT,
    status TEXT DEFAULT 'pending',
    error_message TEXT,
    part_info TEXT DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS subtitles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    language TEXT NOT NULL,
    full_text TEXT NOT NULL,
    segments_json TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    output_type TEXT NOT NULL,
    content TEXT NOT NULL,
    model_used TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS video_tags (
    video_id INTEGER REFERENCES videos(id) ON DELETE CASCADE,
    tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (video_id, tag_id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER REFERENCES videos(id),
    task_type TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    progress REAL DEFAULT 0,
    error_message TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
CREATE INDEX IF NOT EXISTS idx_videos_created ON videos(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_subtitles_video ON subtitles(video_id);
CREATE INDEX IF NOT EXISTS idx_ai_outputs_video_type ON ai_outputs(video_id, output_type);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT DEFAULT 'user',
    daily_limit INTEGER DEFAULT 20,
    is_active INTEGER DEFAULT 1,
    is_deleted INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_login_at DATETIME
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS usage_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    guest_id TEXT,
    action TEXT NOT NULL,
    status TEXT DEFAULT 'SUCCESS',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_usage_user_date ON usage_logs(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_usage_guest_date ON usage_logs(guest_id, created_at);

CREATE TABLE IF NOT EXISTS user_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    guest_id TEXT,
    url_hash TEXT NOT NULL,
    url TEXT NOT NULL,
    video_title TEXT DEFAULT '',
    platform TEXT DEFAULT '',
    is_favorite INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_history_user ON user_history(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_history_guest ON user_history(guest_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_history_url_hash ON user_history(url_hash);
CREATE UNIQUE INDEX IF NOT EXISTS idx_history_user_url ON user_history(user_id, url_hash) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_history_guest_url ON user_history(guest_id, url_hash) WHERE guest_id IS NOT NULL;
"""


@contextmanager
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript(_SCHEMA)
        # 迁移：添加 part_info 列
        try:
            conn.execute("ALTER TABLE videos ADD COLUMN part_info TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
    print(f"[数据库] 初始化完成: {DB_PATH}")


# ──── 字幕持久化查询/写入（供 summarize 和 subtitle 端点复用） ────

def get_or_create_video(url: str, title: str = "", platform: str = "") -> int:
    """获取或创建 video 记录，返回 video_id。"""
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM videos WHERE url = ?", (url,)).fetchone()
        if existing:
            return existing["id"]
        cursor = conn.execute(
            "INSERT INTO videos (url, title, platform) VALUES (?, ?, ?)",
            (url, title, platform),
        )
        return cursor.lastrowid


def get_subtitle_from_db(url: str) -> dict | None:
    """从 subtitles 表查询已缓存的字幕文本。返回 {full_text, source, language, segments} 或 None。"""
    import json as _json
    with get_db() as conn:
        row = conn.execute("""
            SELECT s.full_text, s.source, s.language, s.segments_json
            FROM subtitles s
            JOIN videos v ON s.video_id = v.id
            WHERE v.url = ?
            ORDER BY s.created_at DESC
            LIMIT 1
        """, (url,)).fetchone()
    if not row:
        return None
    segments = []
    if row["segments_json"]:
        try:
            segments = _json.loads(row["segments_json"])
        except (_json.JSONDecodeError, TypeError):
            pass
    return {
        "full_text": row["full_text"],
        "source": row["source"],
        "language": row["language"],
        "segments": segments,
    }


def save_subtitle_to_db(url: str, source: str, language: str, full_text: str, title: str = "", platform: str = "", part_info: str = "", segments: list = None):
    """将字幕文本持久化到 subtitles 表。覆盖同 URL 的旧字幕。"""
    with get_db() as conn:
        # 确保 video 记录存在
        existing = conn.execute("SELECT id, title, platform FROM videos WHERE url = ?", (url,)).fetchone()
        if existing:
            video_id = existing["id"]
            # 补全缺失的 title/platform/part_info
            updates = []
            params = []
            if title and not existing["title"]:
                updates.append("title = ?")
                params.append(title)
            if platform and not existing["platform"]:
                updates.append("platform = ?")
                params.append(platform)
            if part_info:
                updates.append("part_info = ?")
                params.append(part_info)
            if updates:
                params.append(video_id)
                conn.execute(f"UPDATE videos SET {', '.join(updates)} WHERE id = ?", params)
        else:
            cursor = conn.execute(
                "INSERT INTO videos (url, title, platform, part_info) VALUES (?, ?, ?, ?)",
                (url, title, platform, part_info),
            )
            video_id = cursor.lastrowid
        # 先删除该 video 的旧字幕，再插入
        import json as _json
        conn.execute("DELETE FROM subtitles WHERE video_id = ?", (video_id,))
        seg_json = _json.dumps(segments, ensure_ascii=False) if segments else None
        conn.execute(
            "INSERT INTO subtitles (video_id, source, language, full_text, segments_json) VALUES (?, ?, ?, ?, ?)",
            (video_id, source, language, full_text, seg_json),
        )
