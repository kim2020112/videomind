import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import database


MIGRATION_VERSION = "20260713_invalidate_legacy_auth_sessions"


def create_legacy_session_database(path: Path, *, reject_deletes: bool = False) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                daily_limit INTEGER DEFAULT 20,
                is_active INTEGER DEFAULT 1,
                is_deleted INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_login_at DATETIME
            );
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL
            );
            INSERT INTO users (id, username, password_hash)
            VALUES (1, 'legacy-user', 'hash');
            INSERT INTO sessions (id, user_id, expires_at)
            VALUES ('legacy-session', 1, '2099-01-01 00:00:00');
            """
        )
        if reject_deletes:
            conn.execute(
                """
                CREATE TRIGGER reject_session_delete
                BEFORE DELETE ON sessions
                BEGIN
                    SELECT RAISE(FAIL, 'session deletion rejected');
                END
                """
            )


class AuthSessionMigrationTests(unittest.TestCase):
    def test_migration_invalidates_existing_sessions_exactly_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "videomind.db"
            create_legacy_session_database(db_path)

            with patch.object(database, "DB_PATH", db_path):
                database.init_db()

                with sqlite3.connect(db_path) as conn:
                    self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
                    self.assertEqual(
                        1,
                        conn.execute(
                            "SELECT COUNT(*) FROM schema_migrations WHERE version = ?",
                            (MIGRATION_VERSION,),
                        ).fetchone()[0],
                    )
                    conn.execute(
                        "INSERT INTO sessions (id, user_id, expires_at) VALUES (?, ?, ?)",
                        ("post-migration-session", 1, "2099-01-01 00:00:00"),
                    )
                    conn.commit()

                database.init_db()

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(
                    ["post-migration-session"],
                    [row[0] for row in conn.execute("SELECT id FROM sessions")],
                )
                self.assertEqual(
                    1,
                    conn.execute(
                        "SELECT COUNT(*) FROM schema_migrations WHERE version = ?",
                        (MIGRATION_VERSION,),
                    ).fetchone()[0],
                )

    def test_migration_failure_rolls_back_marker_and_is_not_swallowed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "videomind.db"
            create_legacy_session_database(db_path, reject_deletes=True)

            with patch.object(database, "DB_PATH", db_path):
                with self.assertRaisesRegex(sqlite3.IntegrityError, "session deletion rejected"):
                    database.init_db()

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(
                    ["legacy-session"],
                    [row[0] for row in conn.execute("SELECT id FROM sessions")],
                )
                self.assertEqual(
                    0,
                    conn.execute(
                        "SELECT COUNT(*) FROM schema_migrations WHERE version = ?",
                        (MIGRATION_VERSION,),
                    ).fetchone()[0],
                )


if __name__ == "__main__":
    unittest.main()
