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
            "TEMP_DIR": str(temp_root / "temp"),
            "DOWNLOAD_DIR": str(temp_root / "downloads"),
            "WHISPER_MODELS_DIR": str(temp_root / "models"),
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


class JobStoreTests(unittest.TestCase):
    def run_json(self, code: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_backend(code, Path(tmp))
            self.assertEqual(0, result.returncode, result.stderr)
            return json.loads(result.stdout.strip().splitlines()[-1])

    def test_create_get_list_and_duplicate_active_job(self):
        payload = self.run_json(
            """
import json
from core.storage import initialize_storage
from core.job_store import create_job, get_job, list_active_jobs
initialize_storage()
first = create_job('hash-1', 'https://example.com/1', user_id=7, payload={'title': 'demo'})
duplicate = create_job('hash-1', 'https://example.com/1', user_id=7)
other = create_job('hash-2', 'https://example.com/2', guest_id='guest-a')
print(json.dumps({
    'first': first,
    'duplicate': duplicate,
    'job': get_job(first, user_id=7),
    'user_jobs': list_active_jobs(user_id=7),
    'guest_jobs': list_active_jobs(guest_id='guest-a'),
    'other': other,
}))
"""
        )
        self.assertEqual(payload["first"], payload["duplicate"])
        self.assertEqual("demo", payload["job"]["payload"]["title"])
        self.assertEqual([payload["first"]], [job["task_id"] for job in payload["user_jobs"]])
        self.assertEqual([payload["other"]], [job["task_id"] for job in payload["guest_jobs"]])

    def test_claim_is_globally_single_concurrency(self):
        payload = self.run_json(
            """
import json
from core.storage import initialize_storage
from core.job_store import create_job, claim_next_job, update_job
initialize_storage()
first = create_job('hash-1', 'https://example.com/1', user_id=1)
second = create_job('hash-2', 'https://example.com/2', user_id=1)
claimed_first = claim_next_job()
blocked = claim_next_job()
update_job(first, status='done', progress=100)
claimed_second = claim_next_job()
print(json.dumps({
    'first': first,
    'second': second,
    'claimed_first': claimed_first,
    'blocked': blocked,
    'claimed_second': claimed_second,
}))
"""
        )
        self.assertEqual(payload["first"], payload["claimed_first"]["task_id"])
        self.assertIsNone(payload["blocked"])
        self.assertEqual(payload["second"], payload["claimed_second"]["task_id"])

    def test_update_cancel_and_queue_position(self):
        payload = self.run_json(
            """
import json
from core.storage import initialize_storage
from core.job_store import create_job, claim_next_job, get_job, get_queue_position, request_cancel, update_job
initialize_storage()
first = create_job('hash-1', 'https://example.com/1', user_id=1)
second = create_job('hash-2', 'https://example.com/2', user_id=1)
claim_next_job()
update_job(first, status='transcribing', progress=42, message='working')
active_cancel = request_cancel(first, user_id=1)
queued_cancel = request_cancel(second, user_id=1)
print(json.dumps({
    'active': get_job(first, user_id=1),
    'queued': get_job(second, user_id=1),
    'active_cancel': active_cancel,
    'queued_cancel': queued_cancel,
    'position': get_queue_position(second),
}))
"""
        )
        self.assertTrue(payload["active_cancel"])
        self.assertEqual(1, payload["active"]["cancel_requested"])
        self.assertEqual("transcribing", payload["active"]["status"])
        self.assertEqual(42, payload["active"]["progress"])
        self.assertTrue(payload["queued_cancel"])
        self.assertEqual("cancelled", payload["queued"]["status"])
        self.assertIsNone(payload["position"])

    def test_recovery_requeues_interrupted_jobs(self):
        payload = self.run_json(
            """
import json
from core.storage import initialize_storage
from core.job_store import create_job, claim_next_job, get_job, recover_interrupted_jobs, update_job
initialize_storage()
job_id = create_job('hash-1', 'https://example.com/1', user_id=1)
claim_next_job()
update_job(job_id, status='transcribing', progress=55)
recovered = recover_interrupted_jobs()
print(json.dumps({'recovered': recovered, 'job': get_job(job_id, user_id=1)}))
"""
        )
        self.assertEqual(1, payload["recovered"])
        self.assertEqual("queued", payload["job"]["status"])
        self.assertEqual(0, payload["job"]["progress"])
        self.assertEqual(1, payload["job"]["attempts"])
        self.assertIn("重新排队", payload["job"]["message"])


if __name__ == "__main__":
    unittest.main()
