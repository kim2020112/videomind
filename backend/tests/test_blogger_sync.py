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
from core.blogger import store, sync
from core.blogger.catalog import CatalogError


def _entries(start: int, count: int) -> list[dict]:
    return [
        {
            "bvid": f"BV1{start + i:05d}",
            "title": f"视频 {start + i}",
            "pic": "",
            "description": "",
            "created": 1700000000 + start + i,
            "length": "10:00",
        }
        for i in range(count)
    ]


class FakeClient:
    """按页返回预置数据的假目录客户端。"""

    pages: dict[int, tuple[list, int]] = {}
    profile_error: Exception | None = None
    videos_error: Exception | None = None
    calls: list = []
    on_call = None  # 测试钩子：每次 videos() 调用触发

    def __init__(self, *args, **kwargs):
        pass

    def check_session(self):
        return {"isLogin": True}

    def profile(self, uid):
        if self.profile_error:
            raise self.profile_error
        return {"name": f"UP {uid}", "avatar": "http://a", "follower_count": 9}

    def videos(self, uid, page):
        type(self).calls.append(page)
        if type(self).on_call:
            type(self).on_call(page)
        if self.videos_error:
            raise self.videos_error
        return type(self).pages.get(page, ([], 0))

    def parts(self, bvid):
        return {}, []


class BloggerSyncTests(unittest.TestCase):
    def setUp(self):
        self._old_config_db = config.DB_PATH
        self._old_database_db = database.DB_PATH
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "knowledge.db"
        config.DB_PATH = db_path
        database.DB_PATH = db_path
        database.init_db()
        FakeClient.pages = {}
        FakeClient.profile_error = None
        FakeClient.videos_error = None
        FakeClient.calls = []
        FakeClient.on_call = None
        self.creator_id = store.upsert_creator("bilibili", "100")

    def tearDown(self):
        self.tmp.cleanup()
        config.DB_PATH = self._old_config_db
        database.DB_PATH = self._old_database_db

    def _run(self, refresh_profile=True):
        sync_id = store.create_sync(self.creator_id)
        with patch.object(sync, "BilibiliCatalogClient", FakeClient):
            retry = sync.run_sync_blocking(sync_id, self.creator_id, refresh_profile=refresh_profile)
        return sync_id, retry

    def test_syncs_pages_until_short_page(self):
        FakeClient.pages = {
            1: (_entries(0, 30), 45),
            2: (_entries(30, 15), 45),
        }
        sync_id, retry = self._run()
        self.assertIsNone(retry)
        record = store.get_sync(sync_id)
        self.assertEqual("complete", record["status"])
        self.assertEqual(45, record["found"])
        self.assertEqual(45, record["expected"])
        self.assertEqual(2, record["page"])
        self.assertEqual(45, store.list_videos(self.creator_id)["total"])
        self.assertIsNotNone(store.get_creator(self.creator_id)["last_synced_at"])

    def test_empty_catalog_with_expected_marks_api_error(self):
        FakeClient.pages = {1: ([], 12)}
        sync_id, _ = self._run()
        record = store.get_sync(sync_id)
        self.assertEqual("failed", record["status"])
        self.assertEqual("api", record["error_code"])

    def test_network_error_retries_then_fails(self):
        FakeClient.pages = {}
        FakeClient.videos_error = CatalogError("network", "断网")
        sync_id, retry = self._run()
        self.assertEqual(30.0, retry)  # 第一次退避 30s
        self.assertEqual("queued", store.get_sync(sync_id)["status"])
        self.assertEqual(1, store.get_sync(sync_id)["retry_count"])

        # 第二次执行：仍可重试，退避 120s
        with patch.object(sync, "BilibiliCatalogClient", FakeClient):
            retry2 = sync.run_sync_blocking(sync_id, self.creator_id, refresh_profile=False)
        self.assertEqual(120.0, retry2)

        # 第三次执行：已达重试上限
        with patch.object(sync, "BilibiliCatalogClient", FakeClient):
            retry3 = sync.run_sync_blocking(sync_id, self.creator_id, refresh_profile=False)
        self.assertIsNone(retry3)
        self.assertEqual("failed", store.get_sync(sync_id)["status"])

    def test_invalid_session_stops_before_catalog_requests(self):
        sync_id = store.create_sync(self.creator_id)
        with patch.object(sync, "BilibiliCatalogClient", FakeClient), patch.object(
            FakeClient, "check_session", side_effect=CatalogError("login", "登录已失效")
        ):
            retry = sync.run_sync_blocking(sync_id, self.creator_id)
        self.assertIsNone(retry)
        self.assertEqual([], FakeClient.calls)
        self.assertEqual("paused", store.get_sync(sync_id)["status"])
        self.assertEqual("login", store.get_sync(sync_id)["error_code"])

    def test_login_error_pauses_without_retry(self):
        FakeClient.pages = {}
        FakeClient.videos_error = CatalogError("login", "登录失效")
        sync_id, retry = self._run()
        self.assertIsNone(retry)
        record = store.get_sync(sync_id)
        self.assertEqual("paused", record["status"])
        self.assertEqual("login", record["error_code"])

    def test_rate_limit_pauses_without_retry(self):
        FakeClient.pages = {}
        FakeClient.videos_error = CatalogError("rate_limit", "风控")
        sync_id, retry = self._run()
        self.assertIsNone(retry)
        self.assertEqual("paused", store.get_sync(sync_id)["status"])
        self.assertEqual(0, store.get_sync(sync_id)["retry_count"])
        self.assertEqual([1], FakeClient.calls)

    def test_profile_protection_stops_before_catalog_and_does_not_schedule_retry(self):
        for code in ("rate_limit", "budget", "protection"):
            with self.subTest(code=code):
                FakeClient.profile_error = CatalogError(code, "保护已暂停")
                sync_id = store.create_sync(self.creator_id)
                with patch.object(sync, "BilibiliCatalogClient", FakeClient), patch.object(
                    sync.threading, "Timer"
                ) as timer:
                    sync._run_guarded(sync_id, self.creator_id, True)
                timer.assert_not_called()
                self.assertEqual([], FakeClient.calls)
                self.assertEqual("paused", store.get_sync(sync_id)["status"])
                self.assertEqual(code, store.get_sync(sync_id)["error_code"])

    @patch.object(sync, "MAX_PAGES_PER_SYNC", 5)
    def test_page_budget_pauses_and_manual_sync_resumes_saved_cursor(self):
        FakeClient.pages = {
            page: (_entries((page - 1) * 30, 30), 180)
            for page in range(1, 7)
        }
        with patch.object(sync._executor, "submit"):
            sync_id = sync.start_sync(self.creator_id)
        with patch.object(sync, "BilibiliCatalogClient", FakeClient):
            retry = sync.run_sync_blocking(sync_id, self.creator_id, refresh_profile=False)
        self.assertIsNone(retry)
        record = store.get_sync(sync_id)
        self.assertEqual([1, 2, 3, 4, 5], FakeClient.calls)
        self.assertEqual("paused", record["status"])
        self.assertEqual("budget", record["error_code"])
        self.assertEqual(150, record["found"])
        self.assertFalse(store.has_full_catalog_sync(self.creator_id))

        FakeClient.calls = []
        with patch.object(sync._executor, "submit"):
            resumed_id = sync.start_sync(self.creator_id)
        with patch.object(sync, "BilibiliCatalogClient", FakeClient):
            retry = sync.run_sync_blocking(resumed_id, self.creator_id, refresh_profile=False)
        self.assertIsNone(retry)
        self.assertEqual([6], FakeClient.calls)
        record = store.get_sync(resumed_id)
        self.assertEqual("complete", record["status"])
        self.assertEqual(180, record["found"])
        self.assertEqual(180, record["added"])

    @patch.object(sync, "MAX_PAGES_PER_SYNC", 5)
    def test_exact_page_budget_can_complete_without_extra_request(self):
        FakeClient.pages = {
            page: (_entries((page - 1) * 30, 30), 150)
            for page in range(1, 6)
        }
        sync_id, retry = self._run()
        self.assertIsNone(retry)
        self.assertEqual([1, 2, 3, 4, 5], FakeClient.calls)
        self.assertEqual("complete", store.get_sync(sync_id)["status"])

    def test_incremental_budget_resume_does_not_short_circuit_on_newly_saved_page(self):
        self._seed_known(30, start=60)
        baseline = store.create_sync(self.creator_id)
        store.update_sync(baseline, status="complete", found=30, expected=30)
        FakeClient.pages = {
            1: (_entries(0, 30), 90),
            2: (_entries(30, 30), 90),
            3: (_entries(60, 30), 90),
        }
        with patch.object(sync, "MAX_PAGES_PER_SYNC", 1):
            sync_id, _ = self._run()
        self.assertEqual("budget", store.get_sync(sync_id)["error_code"])
        with patch.object(sync._executor, "submit"):
            resumed_id = sync.start_sync(self.creator_id)
        FakeClient.calls = []
        with patch.object(sync, "BilibiliCatalogClient", FakeClient):
            sync.run_sync_blocking(resumed_id, self.creator_id, refresh_profile=False)
        self.assertEqual([2, 3], FakeClient.calls)
        self.assertEqual("deep", store.get_sync(resumed_id)["mode"])
        self.assertEqual(90, store.list_videos(self.creator_id)["total"])

    def test_network_failure_after_progress_pauses_without_automatic_rescan(self):
        FakeClient.pages = {1: (_entries(0, 30), 90)}

        def fail_second_page(page):
            if page == 2:
                raise CatalogError("network", "断网")

        FakeClient.on_call = fail_second_page
        sync_id, retry = self._run(refresh_profile=False)
        self.assertIsNone(retry)
        record = store.get_sync(sync_id)
        self.assertEqual("paused", record["status"])
        self.assertEqual("network", record["error_code"])
        self.assertEqual(1, record["page"])
        self.assertEqual(0, record["retry_count"])

    def test_resume_continues_from_page_cursor(self):
        FakeClient.pages = {
            1: (_entries(0, 30), 60),
            2: (_entries(30, 30), 60),
        }
        sync_id = store.create_sync(self.creator_id)
        store.update_sync(sync_id, mode="deep")
        with patch.object(sync, "BilibiliCatalogClient", FakeClient):
            sync.run_sync_blocking(sync_id, self.creator_id, refresh_profile=False)
        self.assertEqual("complete", store.get_sync(sync_id)["status"])

        # 深度同步模拟中断后的断点：清空 found/expected，保留 page=2 重新同步
        store.update_sync(sync_id, status="interrupted", page=2, found=30, expected=60)
        FakeClient.pages = {3: (_entries(60, 30), 60)}
        FakeClient.calls = []
        with patch.object(sync, "BilibiliCatalogClient", FakeClient):
            sync.run_sync_blocking(sync_id, self.creator_id, refresh_profile=False)
        self.assertEqual([3], FakeClient.calls)  # 从 page=3 继续，不重抓前两页

    def test_repeated_page_signature_stops(self):
        same = _entries(0, 30)
        FakeClient.pages = {1: (same, 90), 2: (same, 90)}
        sync_id, _ = self._run()
        record = store.get_sync(sync_id)
        self.assertEqual("failed", record["status"])
        self.assertIn("重复", record["error"])

    def test_skips_lesson_entries_and_purges_stale(self):
        # 历史误收的课堂推广条目，同步后应被清理
        store.upsert_video(self.creator_id, {"bvid": "BV1lesson0", "title": "课堂推广"})
        lesson_flag = {
            "bvid": "BV1lesson0", "title": "课堂推广", "pic": "", "description": "",
            "created": 1700000000, "length": "00:00",
            "is_lesson_video": 1,
            "jump_url": "https://www.bilibili.com/cheese/play/ss475098271",
        }
        lesson_jump = {
            "bvid": "BV1lesson1", "title": "另一个课堂条目", "pic": "", "description": "",
            "created": 1700000001, "length": "00:00",
            "jump_url": "https://www.bilibili.com/cheese/play/ss12345",
        }
        normal = _entries(0, 2)
        FakeClient.pages = {1: ([lesson_flag, lesson_jump] + normal, 4)}
        sync_id, retry = self._run()
        self.assertIsNone(retry)
        record = store.get_sync(sync_id)
        self.assertEqual("complete", record["status"])
        self.assertEqual(4, record["found"])
        self.assertEqual(2, record["added"])
        listed = store.list_videos(self.creator_id)
        self.assertEqual(2, listed["total"])
        bvids = {item["bvid"] for item in listed["items"]}
        self.assertEqual({"BV100000", "BV100001"}, bvids)

    # ── 增量同步 ──

    def _seed_known(self, count: int, start: int = 0):
        for i in range(start, start + count):
            store.upsert_video(self.creator_id, {"bvid": f"BV1{i:05d}", "title": f"视频 {i}"})

    def test_incremental_short_circuits_on_fully_known_page(self):
        self._seed_known(30)
        baseline = store.create_sync(self.creator_id)
        store.update_sync(baseline, status="complete", found=30, expected=30)
        FakeClient.pages = {1: (_entries(0, 30), 300), 2: (_entries(30, 30), 300)}
        FakeClient.calls = []
        sync_id, retry = self._run()
        self.assertIsNone(retry)
        self.assertEqual([1], FakeClient.calls)  # 整页已收录 → 只抓 1 页
        record = store.get_sync(sync_id)
        self.assertEqual("complete", record["status"])
        self.assertEqual(0, record["added"])
        self.assertEqual("incremental", record["mode"])

    def test_incomplete_catalog_does_not_stop_on_known_first_page(self):
        self._seed_known(30)
        FakeClient.pages = {1: (_entries(0, 30), 45), 2: (_entries(30, 15), 45)}
        sync_id, _ = self._run()
        self.assertEqual([1, 2], FakeClient.calls)
        self.assertEqual(45, store.list_videos(self.creator_id)["total"])
        self.assertTrue(store.has_full_catalog_sync(self.creator_id))

    def test_manual_sync_resumes_incomplete_catalog(self):
        previous = store.create_sync(self.creator_id)
        store.update_sync(previous, status="paused", mode="deep", page=2,
                          found=60, added=60, expected=957, error_code="rate_limit")
        with patch.object(sync._executor, "submit"):
            sync_id = sync.start_sync(self.creator_id)
        record = store.get_sync(sync_id)
        self.assertEqual("deep", record["mode"])
        self.assertEqual(2, record["page"])
        self.assertEqual(60, record["found"])
        self.assertEqual(957, record["expected"])
        self.assertEqual(0, record["retry_count"])

    def test_partial_page_is_not_marked_complete(self):
        FakeClient.pages = {1: (_entries(0, 5), 45)}
        sync_id, _ = self._run()
        self.assertEqual("failed", store.get_sync(sync_id)["status"])
        self.assertFalse(store.has_full_catalog_sync(self.creator_id))

    def test_incremental_scans_new_then_stops_on_known_page(self):
        self._seed_known(30, start=30)  # 第 2 页内容已收录
        FakeClient.pages = {1: (_entries(0, 30), 60), 2: (_entries(30, 30), 60)}
        sync_id, _ = self._run()
        record = store.get_sync(sync_id)
        self.assertEqual("complete", record["status"])
        self.assertEqual(30, record["added"])  # 只有第 1 页是新投稿
        self.assertEqual(2, record["page"])

    def test_deep_mode_does_not_short_circuit(self):
        self._seed_known(30)
        FakeClient.pages = {
            1: (_entries(0, 30), 45),
            2: (_entries(30, 15), 45),
        }
        sync_id = store.create_sync(self.creator_id)
        store.update_sync(sync_id, mode="deep")
        FakeClient.calls = []
        with patch.object(sync, "BilibiliCatalogClient", FakeClient):
            sync.run_sync_blocking(sync_id, self.creator_id, refresh_profile=False)
        self.assertEqual([1, 2], FakeClient.calls)  # 已收录页也继续扫描
        record = store.get_sync(sync_id)
        self.assertEqual("complete", record["status"])
        self.assertEqual(45, record["found"])

    def test_incremental_ignores_page_cursor(self):
        self._seed_known(10)
        sync_id = store.create_sync(self.creator_id)
        store.update_sync(sync_id, status="interrupted", page=5)  # 旧游标
        FakeClient.pages = {1: (_entries(0, 5), 5)}
        FakeClient.calls = []
        with patch.object(sync, "BilibiliCatalogClient", FakeClient):
            sync.run_sync_blocking(sync_id, self.creator_id, refresh_profile=False)
        self.assertEqual([1], FakeClient.calls)  # 增量永远从第 1 页起

    def test_metadata_refresh_keeps_existing_values(self):
        store.upsert_video(self.creator_id, {"bvid": "BV1aaa", "title": "原标题",
                                             "description": "原简介", "duration": 60})
        # arc/search 只带标题：不应抹掉简介/时长
        FakeClient.pages = {1: ([{"bvid": "BV1aaa", "title": "新标题", "pic": "",
                                  "description": "", "created": 0, "length": ""}], 1)}
        self._run()
        item = store.get_video_by_bvid("BV1aaa")
        self.assertEqual("新标题", item["title"])
        self.assertEqual("原简介", item["description"])
        self.assertEqual(60, item["duration"])

    # ── 取消 ──

    def test_cancel_queued_sync_stops_immediately(self):
        sync_id = store.create_sync(self.creator_id, status="queued")
        result = store.cancel_sync(self.creator_id)
        self.assertTrue(result["cancelled"])
        self.assertEqual("cancelled", store.get_sync(sync_id)["status"])
        FakeClient.calls = []
        with patch.object(sync, "BilibiliCatalogClient", FakeClient):
            retry = sync.run_sync_blocking(sync_id, self.creator_id, refresh_profile=False)
        self.assertIsNone(retry)
        self.assertEqual([], FakeClient.calls)  # 不发任何请求

    def test_cancel_running_sync_stops_between_pages(self):
        FakeClient.pages = {
            1: (_entries(0, 30), 90),
            2: (_entries(30, 30), 90),
            3: (_entries(60, 30), 90),
        }
        sync_id = store.create_sync(self.creator_id)

        def on_call(page):
            if page == 2:
                store.cancel_sync(self.creator_id)  # 用户在第 2 页处理期间取消

        FakeClient.on_call = on_call
        FakeClient.calls = []
        try:
            with patch.object(sync, "BilibiliCatalogClient", FakeClient):
                sync.run_sync_blocking(sync_id, self.creator_id, refresh_profile=False)
        finally:
            FakeClient.on_call = None
        record = store.get_sync(sync_id)
        self.assertEqual("cancelled", record["status"])
        self.assertNotIn(3, FakeClient.calls)  # 不再抓后续页


if __name__ == "__main__":
    unittest.main()
