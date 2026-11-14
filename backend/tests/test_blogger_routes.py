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
from core.blogger import store, sync

USER_A = {"user_id": 1, "guest_id": None, "role": "user"}
USER_B = {"user_id": 2, "guest_id": None, "role": "user"}
GUEST = {"user_id": None, "guest_id": "guest-1", "role": "guest"}


class FakeRequest:
    def __init__(self, body=None, query=None):
        self._body = body or {}
        self.query_params = query or {}

    async def json(self):
        return self._body


class BloggerRouteTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_add_blogger_creates_sub_and_starts_sync(self):
        from api import blogger_routes

        with patch.object(blogger_routes, "require_identity", return_value=USER_A):
            with patch.object(blogger_routes.sync, "start_sync", return_value=7) as started:
                response = await blogger_routes.add_blogger(FakeRequest({"input": "475210"}))
        started.assert_called_once()
        self.assertEqual("475210", response["sub"]["uid"])

    async def test_add_blogger_rejects_bad_input(self):
        from api import blogger_routes

        with patch.object(blogger_routes, "require_identity", return_value=USER_A):
            with self.assertRaises(HTTPException) as raised:
                await blogger_routes.add_blogger(FakeRequest({"input": "不存在的昵称"}))
        self.assertEqual(400, raised.exception.status_code)

    async def test_list_is_scoped_to_identity(self):
        from api import blogger_routes

        creator_id = store.upsert_creator("bilibili", "100", name="UP主")
        store.upsert_sub(creator_id, USER_A)
        with patch.object(blogger_routes, "require_identity", return_value=USER_A):
            mine = await blogger_routes.list_bloggers(FakeRequest())
        with patch.object(blogger_routes, "require_identity", return_value=USER_B):
            others = await blogger_routes.list_bloggers(FakeRequest())
        self.assertEqual(1, len(mine["bloggers"]))
        self.assertEqual(0, len(others["bloggers"]))

    async def test_update_alias_and_ownership(self):
        from api import blogger_routes

        creator_id = store.upsert_creator("bilibili", "100")
        sub_id = store.upsert_sub(creator_id, USER_A)

        with patch.object(blogger_routes, "require_identity", return_value=USER_A):
            response = await blogger_routes.update_blogger(sub_id, FakeRequest({"alias": "何同学"}))
        self.assertEqual("何同学", response["sub"]["alias"])

        with patch.object(blogger_routes, "require_identity", return_value=USER_B):
            with self.assertRaises(HTTPException) as raised:
                await blogger_routes.update_blogger(sub_id, FakeRequest({"alias": "偷改"}))
        self.assertEqual(404, raised.exception.status_code)

    async def test_delete_removes_own_sub(self):
        from api import blogger_routes

        creator_id = store.upsert_creator("bilibili", "100")
        sub_id = store.upsert_sub(creator_id, USER_A)
        with patch.object(blogger_routes, "require_identity", return_value=USER_A):
            response = await blogger_routes.delete_blogger(sub_id, FakeRequest())
        self.assertTrue(response["removed"])
        self.assertEqual(0, len(store.list_subs(USER_A)))

    async def test_sync_while_running_is_idempotent(self):
        from api import blogger_routes

        creator_id = store.upsert_creator("bilibili", "100")
        sub_id = store.upsert_sub(creator_id, USER_A)
        existing = store.create_sync(creator_id, status="running")
        with patch.object(blogger_routes, "require_identity", return_value=USER_A):
            with patch.object(blogger_routes.sync, "start_sync") as started:
                response = await blogger_routes.sync_blogger(sub_id, FakeRequest())
        started.assert_not_called()
        self.assertTrue(response["already_running"])
        self.assertEqual(existing, response["sync"]["id"])

    async def test_videos_learned_flags(self):
        from api import blogger_routes
        from core.cache import _url_hash

        creator_id = store.upsert_creator("bilibili", "100")
        sub_id = store.upsert_sub(creator_id, USER_A)
        store.upsert_video(creator_id, {"bvid": "BV1aaa", "title": "已学过"})
        store.upsert_video(creator_id, {"bvid": "BV1bbb", "title": "没学过"})

        url = "https://www.bilibili.com/video/BV1aaa"
        from core.cache import _ensure_table
        _ensure_table()
        with database.get_db() as conn:
            conn.execute(
                "INSERT INTO user_history (user_id, guest_id, url_hash, url, video_title, platform, created_at) "
                "VALUES (1, NULL, ?, ?, '已学过', 'bilibili', '2026-01-01')",
                (_url_hash(url), url),
            )
            conn.execute(
                "INSERT INTO ai_cache (url_hash, url, result_json, created_at, updated_at) "
                "VALUES (?, ?, '{\"result\":{\"summary\":\"已有摘要\"}}', '2026-01-01', '2026-01-01')",
                (_url_hash(url), url),
            )

        with patch.object(blogger_routes, "require_identity", return_value=USER_A):
            response = await blogger_routes.list_blogger_videos(
                sub_id, FakeRequest(query={"limit": "30"})
            )
        by_bvid = {item["bvid"]: item for item in response["items"]}
        self.assertTrue(by_bvid["BV1aaa"]["is_learned"])
        self.assertFalse(by_bvid["BV1bbb"]["is_learned"])
        self.assertEqual(1, response["learned_total"])

    async def test_pages_lazy_loads_and_maps_urls(self):
        from api import blogger_routes

        creator_id = store.upsert_creator("bilibili", "100")
        sub_id = store.upsert_sub(creator_id, USER_A)
        video_id = store.upsert_video(creator_id, {"bvid": "BV1aaa", "title": "多P"})

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def parts(self, bvid):
                return {"title": "多P", "desc": "简介", "pubdate": 1700000000}, [
                    {"cid": 11, "page": 1, "part": "上", "duration": 60},
                    {"cid": 22, "page": 2, "part": "下", "duration": 90},
                ]

        with patch.object(blogger_routes, "require_identity", return_value=USER_A):
            with patch.object(blogger_routes, "BilibiliCatalogClient", FakeClient):
                response = await blogger_routes.list_blogger_video_pages(sub_id, video_id, FakeRequest())
        self.assertEqual(2, len(response["pages"]))
        self.assertEqual("https://www.bilibili.com/video/BV1aaa", response["pages"][0]["url"])
        self.assertEqual("https://www.bilibili.com/video/BV1aaa?p=2", response["pages"][1]["url"])

    async def test_pages_reject_foreign_video(self):
        from api import blogger_routes

        creator_id = store.upsert_creator("bilibili", "100")
        other_creator = store.upsert_creator("bilibili", "200")
        sub_id = store.upsert_sub(creator_id, USER_A)
        foreign_video = store.upsert_video(other_creator, {"bvid": "BV1zzz"})
        with patch.object(blogger_routes, "require_identity", return_value=USER_A):
            with self.assertRaises(HTTPException) as raised:
                await blogger_routes.list_blogger_video_pages(sub_id, foreign_video, FakeRequest())
        self.assertEqual(404, raised.exception.status_code)

    async def test_add_marks_created_and_uses_incremental(self):
        from api import blogger_routes

        with patch.object(blogger_routes, "require_identity", return_value=USER_A):
            with patch.object(blogger_routes.sync, "start_sync", return_value=9) as started:
                response = await blogger_routes.add_blogger(FakeRequest({"input": "475210"}))
        self.assertTrue(response["created"])
        self.assertFalse(response["already_subscribed"])
        started.assert_called_once()
        self.assertEqual("incremental", started.call_args.kwargs.get("mode"))

    async def test_add_duplicate_is_idempotent_without_new_sync(self):
        from api import blogger_routes

        with patch.object(blogger_routes, "require_identity", return_value=USER_A):
            with patch.object(blogger_routes.sync, "start_sync", return_value=9):
                first = await blogger_routes.add_blogger(FakeRequest({"input": "475210"}))
            with patch.object(blogger_routes.sync, "start_sync") as started:
                second = await blogger_routes.add_blogger(FakeRequest({"input": "https://space.bilibili.com/475210"}))
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertTrue(second["already_subscribed"])
        self.assertEqual(first["sub"]["id"], second["sub"]["id"])
        started.assert_not_called()  # 重复添加不再起 conflict 同步

    async def test_preview_reports_profile_and_subscription(self):
        from api import blogger_routes

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            def profile(self, uid):
                return {"name": f"UP {uid}", "avatar": "http://a", "follower_count": 7}

        creator_id = store.upsert_creator("bilibili", "100")
        store.upsert_sub(creator_id, USER_A)

        with patch.object(blogger_routes, "require_identity", return_value=USER_A):
            with patch.object(blogger_routes, "BilibiliCatalogClient", FakeClient):
                fresh = await blogger_routes.preview_blogger(FakeRequest({"input": "475210"}))
                dup = await blogger_routes.preview_blogger(FakeRequest({"input": "100"}))
        self.assertFalse(fresh["already_subscribed"])
        self.assertEqual("475210", fresh["profile"]["uid"])
        self.assertTrue(dup["already_subscribed"])
        self.assertIsNotNone(dup["sub"])
        # preview 不写库
        self.assertEqual(1, len(store.list_subs(USER_A)))

    async def test_preview_rejects_bad_input(self):
        from api import blogger_routes

        with patch.object(blogger_routes, "require_identity", return_value=USER_A):
            with self.assertRaises(HTTPException) as raised:
                await blogger_routes.preview_blogger(FakeRequest({"input": "昵称"}))
        self.assertEqual(400, raised.exception.status_code)

    async def test_sync_status_and_cancel_endpoints(self):
        from api import blogger_routes

        creator_id = store.upsert_creator("bilibili", "100")
        sub_id = store.upsert_sub(creator_id, USER_A)
        sync_id = store.create_sync(creator_id, status="running")
        store.update_sync(sync_id, page=3, found=90, added=2, mode="deep")

        with patch.object(blogger_routes, "require_identity", return_value=USER_A):
            status = await blogger_routes.get_sync_status(sub_id, FakeRequest())
            result = await blogger_routes.cancel_sync(sub_id, FakeRequest())
        self.assertEqual(3, status["sync"]["page"])
        self.assertEqual("deep", status["sync"]["mode"])
        self.assertTrue(result["cancelled"])
        self.assertEqual(1, store.get_sync(sync_id)["cancel_requested"])

    async def test_deletion_preview_counts_and_preserved_note(self):
        from api import blogger_routes

        creator_id = store.upsert_creator("bilibili", "100")
        sub_id = store.upsert_sub(creator_id, USER_A)
        store.upsert_sub(creator_id, USER_B)  # 第二订阅者 → 不级联
        store.upsert_video(creator_id, {"bvid": "BV1aaa"})
        with database.get_db() as conn:
            conn.execute(
                "INSERT INTO blogger_batches (id, user_id, creator_id, mode, selection_json, status, created_at, updated_at) "
                "VALUES ('b1', 1, ?, 'full', '{}', 'done', '2026-01-01', '2026-01-01')",
                (creator_id,),
            )

        with patch.object(blogger_routes, "require_identity", return_value=USER_A):
            preview = await blogger_routes.preview_blogger_deletion(sub_id, FakeRequest())
        self.assertEqual(1, preview["will_remove"]["videos"])
        self.assertEqual(1, preview["will_remove"]["batches"])
        self.assertFalse(preview["cascade"])
        self.assertEqual(1, preview["remaining_subscribers"])
        self.assertTrue(preview["preserved"]["ai_cache"])
        self.assertIn("保留", preview["preserved"]["note"])

    async def test_delete_preserves_learning_content(self):
        from api import blogger_routes
        from core.cache import _ensure_table, _url_hash

        creator_id = store.upsert_creator("bilibili", "100")
        sub_id = store.upsert_sub(creator_id, USER_A)
        url = "https://www.bilibili.com/video/BV1aaa"
        _ensure_table()
        with database.get_db() as conn:
            conn.execute(
                "INSERT INTO user_history (user_id, guest_id, url_hash, url, video_title, platform, created_at) "
                "VALUES (1, NULL, ?, ?, 'T', 'bilibili', '2026-01-01')",
                (_url_hash(url), url),
            )
            conn.execute(
                "INSERT INTO ai_cache (url_hash, url, result_json, created_at, updated_at) "
                "VALUES (?, ?, '{\"result\":{\"summary\":\"已有摘要\"}}', '2026-01-01', '2026-01-01')",
                (_url_hash(url), url),
            )
            video_row = conn.execute(
                "INSERT INTO videos (url, title, platform, created_at, updated_at) "
                "VALUES (?, 'T', 'bilibili', '2026-01-01', '2026-01-01')",
                (url,),
            )
            conn.execute(
                "INSERT INTO subtitles (video_id, source, language, full_text) "
                "VALUES (?, 'bilibili_cc', 'zh', '字幕')",
                (video_row.lastrowid,),
            )

        with patch.object(blogger_routes, "require_identity", return_value=USER_A):
            result = await blogger_routes.delete_blogger(sub_id, FakeRequest())
        self.assertTrue(result["removed"])

        with database.get_db() as conn:
            ai = conn.execute("SELECT COUNT(*) AS n FROM ai_cache").fetchone()["n"]
            history = conn.execute("SELECT COUNT(*) AS n FROM user_history").fetchone()["n"]
            subs_left = conn.execute("SELECT COUNT(*) AS n FROM blogger_subs").fetchone()["n"]
        self.assertEqual(1, ai)       # 学习资料保留
        self.assertEqual(1, history)  # 学习历史保留
        self.assertEqual(0, subs_left)

    async def test_videos_learned_filter_and_count(self):
        from api import blogger_routes
        from core.cache import _ensure_table, _url_hash

        creator_id = store.upsert_creator("bilibili", "100")
        sub_id = store.upsert_sub(creator_id, USER_A)
        store.upsert_video(creator_id, {"bvid": "BV1aaa", "title": "已学过"})
        store.upsert_video(creator_id, {"bvid": "BV1bbb", "title": "没学过"})
        url = "https://www.bilibili.com/video/BV1aaa"
        _ensure_table()
        with database.get_db() as conn:
            conn.execute(
                "INSERT INTO user_history (user_id, guest_id, url_hash, url, video_title, platform, created_at) "
                "VALUES (1, NULL, ?, ?, '已学过', 'bilibili', '2026-01-01')",
                (_url_hash(url), url),
            )
            conn.execute(
                "INSERT INTO ai_cache (url_hash, url, result_json, created_at, updated_at) "
                "VALUES (?, ?, '{\"result\":{\"summary\":\"已有摘要\"}}', '2026-01-01', '2026-01-01')",
                (_url_hash(url), url),
            )

        with patch.object(blogger_routes, "require_identity", return_value=USER_A):
            learned = await blogger_routes.list_blogger_videos(sub_id, FakeRequest(query={"learned": "learned"}))
            unlearned = await blogger_routes.list_blogger_videos(sub_id, FakeRequest(query={"learned": "unlearned"}))
            all_items = await blogger_routes.list_blogger_videos(sub_id, FakeRequest(query={"limit": "30"}))
        self.assertEqual(["BV1aaa"], [v["bvid"] for v in learned["items"]])
        self.assertEqual(["BV1bbb"], [v["bvid"] for v in unlearned["items"]])
        self.assertEqual(2, all_items["total"])
        self.assertEqual(1, all_items["learned_total"])

        # 列表页 learned_count
        with patch.object(blogger_routes, "require_identity", return_value=USER_A):
            listing = await blogger_routes.list_bloggers(FakeRequest())
        self.assertEqual(1, listing["bloggers"][0]["learned_count"])


if __name__ == "__main__":
    unittest.main()
