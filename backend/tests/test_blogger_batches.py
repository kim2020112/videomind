import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import config
import database
from core import job_store
from core.blogger import batches, store

IDENTITY = {"user_id": 1, "guest_id": None}


class FakeClient:
    pages_data: dict[str, list] = {}

    def __init__(self, *args, **kwargs):
        pass

    def parts(self, bvid):
        rows = type(self).pages_data.get(bvid)
        if rows is None:
            return {"title": bvid}, [{"cid": 1, "page": 1, "part": "P1", "duration": 60}]
        return {"title": bvid}, rows


def _setup_creator_with_videos():
    creator_id = store.upsert_creator("bilibili", "100")
    v1 = store.upsert_video(creator_id, {"bvid": "BV1single", "title": "单P"})
    v2 = store.upsert_video(creator_id, {"bvid": "BV1multi", "title": "多P"})
    return creator_id, v1, v2


class BloggerBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (config.DB_PATH, database.DB_PATH, job_store.DB_PATH)
        config.DB_PATH = database.DB_PATH = job_store.DB_PATH = root / "knowledge.db"
        database.init_db()
        FakeClient.pages_data = {
            "BV1multi": [
                {"cid": 11, "page": 1, "part": "上", "duration": 60},
                {"cid": 22, "page": 2, "part": "下", "duration": 90},
            ],
        }
        self.creator_id, self.v1, self.v2 = _setup_creator_with_videos()

    def tearDown(self):
        self.tmp.cleanup()
        config.DB_PATH, database.DB_PATH, job_store.DB_PATH = self._old

    def _create(self, selection, mode="full"):
        with patch.object(batches, "BilibiliCatalogClient", FakeClient):
            return batches.create_batch(self.creator_id, selection, mode=mode, identity=IDENTITY)

    def test_create_freezes_selection_snapshot(self):
        batch = self._create({"video_ids": [self.v1]})
        self.assertEqual(1, batch["total"])
        self.assertEqual(1, len(batch["items"]))
        item = batch["items"][0]
        self.assertEqual("BV1single", item["bvid"])
        self.assertEqual("https://www.bilibili.com/video/BV1single", item["url"])
        self.assertEqual("queued", item["status"])
        self.assertTrue(item["job_id"])

        # 快照已冻结：后续目录新增不影响本批次
        store.upsert_video(self.creator_id, {"bvid": "BV1new", "title": "新增"})
        self.assertEqual(1, len(batches.get_batch(batch["id"], IDENTITY)["items"]))

    def test_multi_part_expansion(self):
        batch = self._create({"video_ids": [self.v2], "include_all_parts": True})
        self.assertEqual(2, batch["total"])
        pages = [(i["bvid"], i["cid"], i["part_index"]) for i in batch["items"]]
        self.assertEqual([("BV1multi", 11, 1), ("BV1multi", 22, 2)], pages)
        self.assertEqual("https://www.bilibili.com/video/BV1multi?p=2", batch["items"][1]["url"])

    def test_include_first_part_only(self):
        batch = self._create({"video_ids": [self.v2], "include_all_parts": False})
        self.assertEqual(1, batch["total"])
        self.assertEqual(1, batch["items"][0]["part_index"])

    def test_exclude_part_ids(self):
        batch = self._create({
            "video_ids": [self.v2], "include_all_parts": True,
            "exclude_part_ids": [f"{self.v2}:2"],
        })
        self.assertEqual(1, batch["total"])
        self.assertEqual(1, batch["items"][0]["part_index"])

    def test_rejects_empty_and_oversized_batches(self):
        with self.assertRaises(ValueError):
            self._create({"video_ids": []})
        with self.assertRaises(ValueError):
            self._create({"video_ids": [self.v1, self.v2], "include_all_parts": True},
                         mode="bad-mode")

    def test_jobs_carry_batch_markers_and_history_queued(self):
        batch = self._create({"video_ids": [self.v1]})
        item = batch["items"][0]
        job = job_store.get_job(item["job_id"], user_id=1)
        self.assertEqual("batch_item", job["job_type"])
        self.assertEqual(batch["id"], job["payload"]["batch_id"])
        self.assertEqual(item["id"], job["payload"]["batch_item_id"])

        from database import get_db
        with get_db() as conn:
            row = conn.execute(
                "SELECT status FROM user_history WHERE user_id = 1 AND url = ?",
                (item["url"],),
            ).fetchone()
        self.assertEqual("queued", row["status"])

    def test_create_job_dedup_backfills_batch_marker(self):
        first = self._create({"video_ids": [self.v1]})
        second = self._create({"video_ids": [self.v1]})
        item1 = first["items"][0]
        item2 = second["items"][0]
        # 同 owner+url_hash 复用同一活跃 job，并回填了第二个批次的标记
        self.assertEqual(item1["job_id"], item2["job_id"])
        job = job_store.get_job(item2["job_id"], user_id=1)
        self.assertEqual(item2["id"], job["payload"]["batch_item_id"])
        self.assertEqual(second["id"], job["payload"]["batch_id"])

    def test_resolve_item_for_job_finalizes_batch(self):
        batch = self._create({"video_ids": [self.v1, self.v2], "include_all_parts": True})
        items = batch["items"]
        job_a = job_store.get_job(items[0]["job_id"], user_id=1)
        job_b = job_store.get_job(items[1]["job_id"], user_id=1)
        job_c = job_store.get_job(items[2]["job_id"], user_id=1)

        batches.resolve_item_for_job(job_a, "done")
        batches.resolve_item_for_job(job_b, "failed", "boom")
        mid = batches.get_batch(batch["id"], IDENTITY)
        self.assertEqual("running", mid["status"])

        batches.resolve_item_for_job(job_c, "done")
        final = batches.get_batch(batch["id"], IDENTITY)
        self.assertEqual("failed", final["status"])  # 有失败条目
        self.assertEqual(2, final["done_count"])
        self.assertEqual(1, final["failed_count"])

    def test_resolve_is_idempotent_and_skips_overwrite(self):
        batch = self._create({"video_ids": [self.v1]})
        item = batch["items"][0]
        job = job_store.get_job(item["job_id"], user_id=1)
        batches.update_item(item["id"], status="skipped", error_code="usage_limit")
        batches.resolve_item_for_job(job, "done")  # 不覆盖 skipped
        refreshed = batches.get_batch(batch["id"], IDENTITY)["items"][0]
        self.assertEqual("skipped", refreshed["status"])
        batches.resolve_item_for_job(job, "failed", "x")  # 幂等，不重复变更
        self.assertEqual("skipped", batches.get_batch(batch["id"], IDENTITY)["items"][0]["status"])

    def test_batch_action_state_machine(self):
        batch = self._create({"video_ids": [self.v1, self.v2], "include_all_parts": True})
        batch_id = batch["id"]

        batches.batch_action(batch_id, "pause", IDENTITY)
        paused = batches.get_batch(batch_id, IDENTITY)
        self.assertEqual("paused", paused["status"])
        self.assertTrue(all(i["status"] == "paused" for i in paused["items"]))

        batches.batch_action(batch_id, "resume", IDENTITY)
        resumed = batches.get_batch(batch_id, IDENTITY)
        self.assertIn(resumed["status"], ("queued", "running"))
        self.assertTrue(all(i["status"] == "queued" for i in resumed["items"]))
        self.assertTrue(all(i["job_id"] for i in resumed["items"]))

        batches.batch_action(batch_id, "cancel", IDENTITY)
        cancelled = batches.get_batch(batch_id, IDENTITY)
        self.assertEqual("cancelled", cancelled["status"])
        self.assertTrue(all(i["status"] == "cancelled" for i in cancelled["items"]))

    def test_retry_failed_respects_limit(self):
        batch = self._create({"video_ids": [self.v1]})
        item = batch["items"][0]
        batches.update_item(item["id"], status="failed", error="x")
        # retry_count=0 时允许重试一次
        batches.batch_action(batch["id"], "retry_failed", IDENTITY)
        refreshed = batches.get_batch(batch["id"], IDENTITY)["items"][0]
        self.assertEqual("queued", refreshed["status"])
        self.assertEqual(1, refreshed["retry_count"])

        batches.update_item(refreshed["id"], status="failed", error="x")
        batches.batch_action(batch["id"], "retry_failed", IDENTITY)
        again = batches.get_batch(batch["id"], IDENTITY)["items"][0]
        self.assertEqual(2, again["retry_count"])
        batches.update_item(again["id"], status="failed", error="x")
        with self.assertRaises(ValueError):
            batches.batch_action(batch["id"], "retry_failed", IDENTITY)

    def test_ownership_isolation(self):
        batch = self._create({"video_ids": [self.v1]})
        self.assertIsNone(batches.get_batch(batch["id"], {"user_id": 2, "guest_id": None}))
        with self.assertRaises(ValueError):
            batches.batch_action(batch["id"], "cancel", {"user_id": 2, "guest_id": None})

    def test_reconcile_requeues_orphaned_items(self):
        batch = self._create({"video_ids": [self.v1]})
        item = batch["items"][0]
        # 模拟崩溃：job 被清理但条目仍在排队
        job_store.update_job(item["job_id"], status="failed", error="crash")
        batches.update_item(item["id"], status="queued", job_id=None)
        fixed = batches.reconcile_batches()
        self.assertGreaterEqual(fixed, 1)
        refreshed = batches.get_batch(batch["id"], IDENTITY)["items"][0]
        self.assertEqual("queued", refreshed["status"])
        self.assertTrue(refreshed["job_id"])

    def test_pause_for_usage_limit(self):
        batch = self._create({"video_ids": [self.v1, self.v2], "include_all_parts": True})
        items = batch["items"]
        batches.pause_batch_for_usage_limit(batch["id"], items[0]["id"])
        refreshed = batches.get_batch(batch["id"], IDENTITY)
        statuses = [i["status"] for i in refreshed["items"]]
        self.assertEqual("skipped", statuses[0])
        self.assertTrue(all(s == "paused" for s in statuses[1:]))
        self.assertEqual("paused", refreshed["status"])
        self.assertEqual("usage_limit", refreshed["items"][0]["error_code"])

    def test_resume_requeues_usage_limit_skipped_items(self):
        # 额度暂停时排队 job 空转后会把条目记为 skipped+usage_limit，
        # resume 必须把它们与 paused 条目一起恢复
        batch = self._create({"video_ids": [self.v1, self.v2], "include_all_parts": True})
        items = batch["items"]
        batches.pause_batch_for_usage_limit(batch["id"], items[0]["id"])
        batches.update_item(items[1]["id"], status="skipped", error_code="usage_limit")

        batches.batch_action(batch["id"], "resume", IDENTITY)
        refreshed = batches.get_batch(batch["id"], IDENTITY)
        self.assertIn(refreshed["status"], ("queued", "running"))
        self.assertTrue(all(i["status"] == "queued" for i in refreshed["items"]))

    def test_resolve_finalizes_all_items_sharing_job(self):
        # 同 owner+url_hash 去重复用 job 时，两个批次的条目共享 job_id，
        # 终态回写必须逐条结算，否则先入批次的条目永久悬挂
        first = self._create({"video_ids": [self.v1]})
        second = self._create({"video_ids": [self.v1]})
        item1 = first["items"][0]
        item2 = second["items"][0]
        self.assertEqual(item1["job_id"], item2["job_id"])

        job = job_store.get_job(item2["job_id"], user_id=1)
        batches.resolve_item_for_job(job, "done")
        self.assertEqual("done", batches.get_batch(first["id"], IDENTITY)["items"][0]["status"])
        self.assertEqual("done", batches.get_batch(second["id"], IDENTITY)["items"][0]["status"])


if __name__ == "__main__":
    unittest.main()
