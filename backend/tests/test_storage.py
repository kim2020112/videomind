import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def run_backend(code: str, temp_root: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(BACKEND),
            "DB_PATH": str(temp_root / "db" / "knowledge.db"),
            "AI_CONFIG_PATH": str(temp_root / "config" / "ai_config.json"),
            "TEMP_DIR": str(temp_root / "temp"),
            "DOWNLOAD_DIR": str(temp_root / "downloads"),
            "WHISPER_MODELS_DIR": str(temp_root / "models"),
            "FEATURE_AI": "false",
            "FEATURE_WHISPER": "false",
        }
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )


class StorageLifecycleTests(unittest.TestCase):
    def test_import_main_does_not_create_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_backend("import main; print('ok')", root)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("ok", result.stdout)
            self.assertFalse((root / "db" / "knowledge.db").exists())

    def test_initialize_storage_creates_database_and_cache_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code = """
import json, sqlite3
from core.storage import initialize_storage
from config import DB_PATH
initialize_storage()
with sqlite3.connect(DB_PATH) as conn:
    tables = sorted(r[0] for r in conn.execute(
        \"SELECT name FROM sqlite_master WHERE type='table'\"
    ))
print(json.dumps({\"db\": str(DB_PATH), \"tables\": tables}))
"""
            result = run_backend(code, root)
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertTrue(Path(payload["db"]).exists())
            self.assertIn("videos", payload["tables"])
            self.assertIn("ai_cache", payload["tables"])
            self.assertIn("whisper_cache", payload["tables"])

    def test_readiness_reports_storage_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code = """
import json
from core.storage import initialize_storage, check_readiness
initialize_storage()
print(json.dumps(check_readiness()))
"""
            result = run_backend(code, root)
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertTrue(payload["ready"])
            self.assertTrue(payload["checks"]["database"])
            self.assertTrue(payload["checks"]["temp_dir"])
            self.assertTrue(payload["checks"]["download_dir"])

    def test_readiness_rejects_database_without_write_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code = """
import json, sqlite3
from unittest.mock import patch
from core.storage import initialize_storage, check_readiness

class ReadOnlyConnection:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def execute(self, sql):
        if sql.startswith("UPDATE users"):
            raise sqlite3.OperationalError("attempt to write a readonly database")
        return self
    def fetchone(self):
        return (1,)
    def rollback(self):
        pass

initialize_storage()
with patch("core.storage.sqlite3.connect", return_value=ReadOnlyConnection()):
    print(json.dumps(check_readiness()))
"""
            result = run_backend(code, root)
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertFalse(payload["ready"])
            self.assertFalse(payload["checks"]["database"])
            self.assertTrue(any("readonly" in error for error in payload["errors"]))


if __name__ == "__main__":
    unittest.main()
