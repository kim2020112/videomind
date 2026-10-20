import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import config
import database
from core.blogger import store


USER_A = {"user_id": 1, "guest_id": None}
USER_B = {"user_id": 2, "guest_id": None}
GUEST = {"user_id": None, "guest_id": "guest-1"}
GUEST_OTHER = {"user_id": None, "guest_id": "guest-2"}


class BloggerStoreTests(unittest.TestCase):
    def setUp(self):
        self._old_config_db = config.DB_PATH
        self._old_database_db = database.DB_PATH
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "knowledge.db"
        config.DB_PATH = db_path
        database.DB_PATH = db_path
        database.init_db()

    def tearDown(self):
        self.tmp.cleanup()
        config.DB_PATH = self._old_config_db
        database.DB_PATH = self._old_database_db

    def test_subs_are_isolated_per_identity(self):
        creator_id = store.upsert_creator("bilibili", "100")
        store.upsert_sub(creator_id, USER_A)
        store.upsert_sub(creator_id, GUEST)

        self.assertEqual(1, len(store.list_subs(USER_A)))
        self.assertEqual(1, len(store.list_subs(GUEST)))
        self.assertEqual(0, len(store.list_subs(USER_B)))
        self.assertEqual(0, len(store.list_subs(GUEST_OTHER)))

    def test_upsert_sub_is_idempotent(self):
        creator_id = store.upsert_creator("bilibili", "100")
        first = store.upsert_sub(creator_id, USER_A)
        second = store.upsert_sub(creator_id, USER_A)
        self.assertEqual(first, second)
        self.assertEqual(1, len(store.list_subs(USER_A)))

    def test_alias_survives_creator_refresh(self):
        creator_id = store.upsert_creator("bilibili", "100", name="旧名字")
        sub_id = store.upsert_sub(creator_id, USER_A, alias="我的备注")
        store.upsert_creator("bilibili", "100", name="新名字")

        sub = store.get_sub(sub_id, USER_A)
        self.assertEqual("我的备注", sub["alias"])
        self.assertEqual("新名字", sub["name"])

    def test_upsert_creator_preserves_follower_count_without_refresh(self):
        creator_id = store.upsert_creator("bilibili", "100", name="UP", follower_count=5200)
        # 他人重新订阅时以默认值 upsert，不应清零已同步的粉丝数
        store.upsert_creator("bilibili", "100")
        self.assertEqual(5200, store.get_creator(creator_id)["follower_count"])
        # 同步携带真实值时正常更新
        store.upsert_creator("bilibili", "100", follower_count=6300)
        self.assertEqual(6300, store.get_creator(creator_id)["follower_count"])

    def test_remove_sub_keeps_shared_catalog_until_last_subscriber(self):
        creator_id = store.upsert_creator("bilibili", "100")
        store.upsert_video(creator_id, {"bvid": "BV1aaa", "title": "视频"})
        sub_a = store.upsert_sub(creator_id, USER_A)
        sub_b = store.upsert_sub(creator_id, USER_B)

        result = store.remove_sub(sub_a, USER_A)
        self.assertTrue(result["removed"])
        self.assertFalse(result["cascade"])
        self.assertIsNotNone(store.get_creator(creator_id))
        self.assertEqual(1, len(store.list_videos(creator_id)["items"]))

        result = store.remove_sub(sub_b, USER_B)
        self.assertTrue(result["cascade"])
        self.assertIsNone(store.get_creator(creator_id))
        self.assertEqual(0, len(store.list_videos(creator_id)["items"]))

    def test_remove_sub_blocks_cascade_while_batch_active(self):
        creator_id = store.upsert_creator("bilibili", "100")
        sub_id = store.upsert_sub(creator_id, USER_A)
        with database.get_db() as conn:
            conn.execute(
                "INSERT INTO blogger_batches (id, user_id, creator_id, mode, selection_json, status, created_at, updated_at) "
                "VALUES ('b1', 1, ?, 'full', '{}', 'running', '2026-01-01', '2026-01-01')",
                (creator_id,),
            )
        result = store.remove_sub(sub_id, USER_A)
        self.assertTrue(result["removed"])
        self.assertFalse(result["cascade"])
        self.assertIsNotNone(store.get_creator(creator_id))

    def test_remove_sub_cascades_finished_batches(self):
        """已结束批次不再阻塞退订；级联删除不能被批次外键卡住。"""
        creator_id = store.upsert_creator("bilibili", "100")
        store.upsert_video(creator_id, {"bvid": "BV1aaa"})
        sub_id = store.upsert_sub(creator_id, USER_A)
        with database.get_db() as conn:
            conn.execute(
                "INSERT INTO blogger_batches (id, user_id, creator_id, mode, selection_json, status, created_at, updated_at) "
                "VALUES ('b-done', 1, ?, 'full', '{}', 'done', '2026-01-01', '2026-01-01')",
                (creator_id,),
            )
            conn.execute(
                "INSERT INTO blogger_batch_items (id, batch_id, position, url, url_hash, status, created_at, updated_at) "
                "VALUES ('i1', 'b-done', 0, 'https://e.com/1', 'h1', 'done', '2026-01-01', '2026-01-01')",
            )
        result = store.remove_sub(sub_id, USER_A)
        self.assertTrue(result["removed"])
        self.assertTrue(result["cascade"])
        self.assertIsNone(store.get_creator(creator_id))
        with database.get_db() as conn:
            leftovers = conn.execute("SELECT COUNT(*) AS n FROM blogger_batch_items").fetchone()["n"]
            batches_left = conn.execute("SELECT COUNT(*) AS n FROM blogger_batches").fetchone()["n"]
        self.assertEqual(0, leftovers)
        self.assertEqual(0, batches_left)

    def test_cannot_update_or_remove_others_sub(self):
        creator_id = store.upsert_creator("bilibili", "100")
        sub_id = store.upsert_sub(creator_id, USER_A)

        self.assertFalse(store.update_sub(sub_id, USER_B, alias="偷改"))
        self.assertFalse(store.remove_sub(sub_id, GUEST)["removed"])
        self.assertIsNotNone(store.get_sub(sub_id, USER_A))

    def test_video_upsert_updates_metadata(self):
        creator_id = store.upsert_creator("bilibili", "100")
        first = store.upsert_video(creator_id, {"bvid": "BV1aaa", "title": "旧标题", "duration": 10})
        second = store.upsert_video(creator_id, {"bvid": "BV1aaa", "title": "新标题", "duration": 20})
        self.assertEqual(first, second)
        item = store.get_video_by_bvid("BV1aaa")
        self.assertEqual("新标题", item["title"])
        self.assertEqual(20, item["duration"])

    def test_pages_roundtrip_and_page_count(self):
        creator_id = store.upsert_creator("bilibili", "100")
        video_id = store.upsert_video(creator_id, {"bvid": "BV1aaa", "title": "多P"})
        self.assertFalse(store.has_pages(video_id))
        store.replace_pages(video_id, [
            {"cid": 11, "page": 1, "part_title": "上", "duration": 60},
            {"cid": 22, "page": 2, "part_title": "下", "duration": 90},
        ])
        self.assertTrue(store.has_pages(video_id))
        rows = store.list_pages(video_id)
        self.assertEqual([11, 22], [row["cid"] for row in rows])
        self.assertEqual(2, store.get_video(video_id)["page_count"])

    def test_recover_stale_syncs(self):
        creator_id = store.upsert_creator("bilibili", "100")
        sync_id = store.create_sync(creator_id, status="running")
        self.assertEqual(1, store.recover_stale_syncs())
        self.assertEqual("interrupted", store.get_sync(sync_id)["status"])


if __name__ == "__main__":
    unittest.main()
