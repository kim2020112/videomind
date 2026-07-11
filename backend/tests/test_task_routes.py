import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import config
import database
from core import job_store


class TaskRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "knowledge.db"
        config.DB_PATH = db_path
        database.DB_PATH = db_path
        job_store.DB_PATH = db_path
        database.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    async def test_active_tasks_are_owner_scoped(self):
        from api import task_routes

        own_id = job_store.create_job("hash-1", "https://example.com/1", user_id=1)
        job_store.create_job("hash-2", "https://example.com/2", user_id=2)
        with patch.object(task_routes, "require_identity", return_value={"user_id": 1, "guest_id": None}):
            response = await task_routes.get_active_tasks(object())

        self.assertEqual([own_id], [job["task_id"] for job in response["tasks"]])

    async def test_status_lookup_does_not_expose_other_owner(self):
        from api import task_routes

        job_id = job_store.create_job("hash-1", "https://example.com/1", user_id=2)
        with patch.object(task_routes, "require_identity", return_value={"user_id": 1, "guest_id": None}):
            with self.assertRaises(HTTPException) as raised:
                await task_routes.get_task_status(job_id, object())

        self.assertEqual(404, raised.exception.status_code)

    async def test_cancel_marks_queued_job_cancelled(self):
        from api import task_routes

        job_id = job_store.create_job("hash-1", "https://example.com/1", guest_id="guest-a")
        identity = {"user_id": None, "guest_id": "guest-a"}
        with patch.object(task_routes, "require_identity", return_value=identity):
            response = await task_routes.cancel_task(job_id, object())

        self.assertEqual("cancelled", response["status"])
        self.assertEqual("cancelled", job_store.get_job(job_id, guest_id="guest-a")["status"])


if __name__ == "__main__":
    unittest.main()
