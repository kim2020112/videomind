"""Runtime storage initialization and readiness checks."""

import os
import sqlite3
import tempfile
from pathlib import Path

from config import DB_PATH, DOWNLOAD_DIR, TEMP_DIR, ensure_directories
from core.cache import init_cache
from database import init_db


def initialize_storage() -> None:
    """Create runtime directories and initialize all SQLite schemas."""
    ensure_directories()
    init_db()
    init_cache()


def _directory_is_writable(path: Path) -> bool:
    try:
        fd, probe = tempfile.mkstemp(prefix=".ready-", dir=str(path))
        os.close(fd)
        os.unlink(probe)
        return True
    except OSError:
        return False


def check_readiness() -> dict:
    """Return database connectivity and runtime directory write status."""
    checks = {
        "database": False,
        "temp_dir": False,
        "download_dir": False,
    }
    errors = []

    try:
        with sqlite3.connect(str(DB_PATH), timeout=5) as conn:
            conn.execute("SELECT 1").fetchone()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE users SET username = username WHERE 0")
            conn.rollback()
        checks["database"] = True
    except (OSError, sqlite3.Error) as exc:
        errors.append(f"database: {exc}")

    for name, path in (("temp_dir", TEMP_DIR), ("download_dir", DOWNLOAD_DIR)):
        if path.is_dir() and _directory_is_writable(path):
            checks[name] = True
        else:
            errors.append(f"{name}: not writable ({path})")

    return {
        "ready": all(checks.values()),
        "checks": checks,
        "errors": errors,
    }
