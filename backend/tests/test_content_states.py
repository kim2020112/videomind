import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
import database
from core import cache, learning, job_store
from core.auth import add_user_history
from core.blogger import store, learned
from core.content_state import content_state
from api import blogger_routes, learning_routes

A = {"user_id": None, "guest_id": "reader-a"}
B = {"user_id": None, "guest_id": "reader-b"}
URL = "https://www.bilibili.com/video/BV1state"


class Request:
    def __init__(self, **query):
        self.query_params = query


class ContentStateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / 'test.db'
        for module in (database, config, job_store):
            patcher = patch.object(module, 'DB_PATH', path)
            patcher.start()
            self.addCleanup(patcher.stop)
        database.init_db()
        cache._ensure_table()
        cache._ensure_video_info_table()
        self.creator = store.upsert_creator('bilibili', '99')
        self.sub = store.upsert_sub(self.creator, A)

    def save(self, url=URL, payload=None, text='', source='bilibili_cc', identity=A, status='done'):
        cache.save_cache(url, result_json=json.dumps(payload or {}), subtitle_text=text, source=source)
        add_user_history(**identity, url_hash=cache._url_hash(url), url=url, status=status)

    async def listing(self, **query):
        with patch.object(blogger_routes, 'require_identity', return_value=A):
            return await blogger_routes.list_blogger_videos(self.sub, Request(**query))

    def test_content_semantics_exclude_empty_malformed_and_description(self):
        for payload in ('{}', '[]', 'null', '{bad', {'notes': '  ', 'qa_pairs': []}, {'result': {'summary': ''}}):
            self.assertEqual(0, content_state(payload)['module_count'])
        state = content_state({'description_summary': {'summary': '简介'}})
        self.assertTrue(state['has_description_summary'])
        self.assertEqual('empty', state['coverage'])
        self.assertEqual('subtitle', content_state(has_subtitle=True)['coverage'])
        state = content_state({'result': {'summary': '摘要'}, 'notes': '笔记'})
        self.assertEqual(['summary', 'notes'], state['modules'])
        self.assertEqual(2, state['module_count'])

    async def test_catalog_filters_counts_and_exact_part_ownership(self):
        for bvid in ('BV1state', 'BV1stateLonger', 'BV1empty', 'BV1description', 'BV1other'):
            store.upsert_video(self.creator, {'bvid': bvid, 'title': bvid})
        self.save(payload={'notes': '笔记'}, text='字幕', status='failed')
        self.save(URL+'?p=2', {'mindmap_markdown': '# 导图'}, 'P2字幕')
        self.save(URL+'?p=3', text='只有字幕')
        self.save(URL.replace('BV1state', 'BV1empty'))
        self.save(URL.replace('BV1state', 'BV1description'), {'description_summary': {'summary': '简介'}}, '简介原文', source='description')
        self.save(URL.replace('BV1state', 'BV1other'), {'notes': '另一身份'}, '他人字幕', identity=B)
        all_items = await self.listing()
        indexed = {item['bvid']: item for item in all_items['items']}
        self.assertEqual([1, 2], indexed['BV1state']['organized_parts'])
        self.assertEqual([1, 2, 3], indexed['BV1state']['subtitle_parts'])
        self.assertEqual(1, indexed['BV1state']['content']['module_count'])
        self.assertFalse(indexed['BV1stateLonger']['is_learned'])
        self.assertFalse(indexed['BV1other']['is_learned'])
        self.assertEqual(1, all_items['organized_total'])
        self.assertEqual(1, all_items['subtitle_total'])
        self.assertEqual(5, all_items['matched_total'])
        filtered = await self.listing(learned='learned', has_subtitle='1')
        self.assertEqual(['BV1state'], [i['bvid'] for i in filtered['items']])
        self.assertEqual(0, (await self.listing(learned='unlearned', has_subtitle='1'))['total'])
        state = learned.content_by_bvid(B, ['BV1state'])
        self.assertEqual({}, state)
        with patch.object(blogger_routes, 'require_identity', return_value=A):
            cards = await blogger_routes.list_bloggers(Request())
        self.assertEqual(1, cards['bloggers'][0]['organized_count'])
        self.assertEqual(1, cards['bloggers'][0]['subtitle_count'])

    async def test_anchor_index_uses_current_sort_and_filters(self):
        for i in range(24):
            store.upsert_video(self.creator, {'bvid': f'BV1anchor{i}', 'title': f'第{i}集', 'published_at': 100+i})
        result = await self.listing(limit='5')
        target = result['items'][3]['id']
        self.assertEqual(3, (await self.listing(anchor_id=str(target)))['anchor_index'])
        self.assertIsNone((await self.listing(anchor_id=str(target), learned='learned'))['anchor_index'])
        store.upsert_video(self.creator, {'bvid': 'BV1new', 'title': '最新', 'published_at': 999})
        self.assertEqual(4, (await self.listing(anchor_id=str(target)))['anchor_index'])

    async def test_locate_anchor_returns_one_aligned_page_and_clamps_deleted_tail(self):
        for i in range(65):
            store.upsert_video(self.creator, {'bvid': f'BVdeep{i}', 'title': f'课程{i}', 'published_at': 100+i})
        ordered = store.list_videos(self.creator, limit=100)['items']
        target = ordered[47]['id']
        result = await self.listing(anchor_id=str(target), locate_anchor='1', offset='0', limit='20')
        self.assertEqual(47, result['anchor_index'])
        self.assertEqual(40, result['offset'])
        self.assertEqual(20, result['limit'])
        self.assertEqual(20, len(result['items']))
        self.assertIn(target, [item['id'] for item in result['items']])
        tail = await self.listing(offset='99999', limit='20')
        self.assertEqual(((tail['total'] - 1) // 20) * 20, tail['offset'])
        self.assertTrue(tail['items'])

    async def test_visit_shared_subtitle_is_idempotent_and_free(self):
        database.save_subtitle_to_db(URL, 'bilibili_cc', 'zh', '共享字幕', '测试', 'bilibili')
        with patch.object(learning_routes, 'require_identity', return_value=A), patch.object(learning_routes, 'normalize', return_value=URL):
            for _ in range(2):
                response = await learning_routes.visit_workspace(learning_routes.VisitRequest(url=URL), Request())
                self.assertTrue(response['recorded'])
        with database.get_db() as conn:
            self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM user_history').fetchone()[0])
            for table in ('background_jobs', 'usage_logs', 'learning_usage'):
                self.assertEqual(0, conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0])
            conn.execute("UPDATE user_history SET status='failed', is_favorite=1")
        learning.record_visit(URL, A)
        with database.get_db() as conn:
            row = conn.execute('SELECT status, is_favorite FROM user_history').fetchone()
            self.assertEqual(('failed', 1), tuple(row))
        self.assertFalse(learning.record_visit(URL+'/missing', B)['recorded'])

    def test_visit_shared_artifact_records_only_current_identity(self):
        cache.save_cache(URL, result_json=json.dumps({'notes': '共享笔记'}))
        state = learning.record_visit(URL, A)
        self.assertTrue(state['recorded'])
        self.assertEqual(1, state['content']['module_count'])
        self.assertEqual({}, learned.content_by_bvid(B, ['BV1state']))
        self.assertEqual(1, learned.content_by_bvid(A, ['BV1state'])['BV1state'][1]['module_count'])

    def test_stale_saved_module_still_counts(self):
        payload = {'notes': '旧笔记', '_artifacts': {'notes': {'subtitle_revision': learning.revision('旧字幕'), 'prompt_version': learning.prompt_version('notes')}}}
        state = content_state(payload, True, '新字幕')
        self.assertEqual(1, state['module_count'])
        self.assertEqual(['notes'], state['stale_modules'])
        self.assertEqual([], content_state(payload, True, '旧字幕')['stale_modules'])

    def test_subtitle_only_and_description_are_not_learning_history(self):
        self.save(text='只有字幕')
        self.save(URL+'?p=2', {'description_summary': {'summary': '简介摘要'}}, source='description')
        for role in ('guest', 'admin'):
            result = cache.list_history_enhanced(**A, role=role)
            self.assertEqual(0, result['total'])
        self.assertEqual(0, cache.get_learning_stats(**A)['total_videos'])
        self.save(URL+'?p=3', {'notes': '已整理笔记'}, status='failed')
        result = cache.list_history_enhanced(**A)
        self.assertEqual(1, result['total'])
        self.assertEqual(URL+'?p=3', result['items'][0]['url'])
        self.assertEqual(1, result['items'][0]['content']['module_count'])
        self.assertEqual(1, cache.get_learning_stats(**A)['total_videos'])
        self.assertEqual(1, cache.list_history_enhanced(**A, limit=1)['total'])

    async def test_clear_subtitle_is_personal_idempotent_and_survives_visits(self):
        store.upsert_video(self.creator, {'bvid': 'BV1state', 'title': '视频'})
        self.save(text='共享字幕')
        learning.record_visit(URL, B)
        with patch.object(learning_routes, 'require_identity', return_value=A), patch.object(learning_routes, 'normalize', return_value=URL):
            for _ in range(2):
                result = await learning_routes.clear_workspace_subtitle(learning_routes.VisitRequest(url=URL), Request())
                self.assertTrue(result['subtitle_cleared'])
                self.assertIsNone(result['subtitle'])
        learning.record_visit(URL, A)
        self.assertTrue(learning.workspace(URL, A)['subtitle_cleared'])
        self.assertIsNone(learning.workspace(URL, A)['subtitle'])
        self.assertEqual('共享字幕', learning.workspace(URL, B)['subtitle']['text'])
        listing = await self.listing()
        self.assertEqual([], listing['items'][0]['subtitle_parts'])
        self.assertEqual(0, listing['subtitle_total'])
        self.assertEqual(0, cache.list_history_enhanced(**A)['total'])
        self.assertEqual(0, (await self.listing(has_subtitle='1'))['total'])
        with database.get_db() as conn:
            self.assertEqual('共享字幕', conn.execute('SELECT subtitle_text FROM ai_cache').fetchone()[0])
            for table in ('background_jobs', 'usage_logs', 'learning_usage'):
                self.assertEqual(0, conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0])

    def test_clear_keeps_ai_artifacts_favorite_and_other_parts(self):
        payload = {'notes': '保留笔记', '_artifacts': {'notes': {'subtitle_revision': learning.revision('字幕'), 'prompt_version': learning.prompt_version('notes')}}}
        self.save(payload=payload, text='字幕')
        self.save(URL+'?p=1', payload, '字幕')
        self.save(URL+'?p=2', {'mindmap_markdown': '# P2'}, 'P2字幕')
        with database.get_db() as conn:
            conn.execute("UPDATE user_history SET is_favorite=1, status='failed'")
        result = learning.clear_subtitle(URL+'?p=1', A)
        self.assertIsNone(result['subtitle'])
        self.assertEqual('保留笔记', result['artifacts']['notes'])
        self.assertFalse(result['modules']['notes']['stale'])
        self.assertTrue(learning.workspace(URL, A)['subtitle_cleared'])
        self.assertFalse(learning.workspace(URL+'?p=2', A)['subtitle_cleared'])
        content = learned.content_by_bvid(A, ['BV1state'])['BV1state']
        self.assertFalse(content[1]['has_subtitle'])
        self.assertTrue(content[2]['has_subtitle'])
        self.assertEqual(1, content[1]['module_count'])
        history = cache.list_history_enhanced(**A)
        self.assertEqual(1, history['total'])
        with database.get_db() as conn:
            self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM user_history WHERE is_favorite!=1 OR status!='failed'").fetchone()[0])

    async def test_clear_rejects_an_active_task_without_changing_state(self):
        self.save(text='字幕')
        from core import job_store
        task = job_store.create_job(cache._url_hash(URL), URL, **A, payload={'targets': []}, job_type='learning')
        with patch.object(learning_routes, 'require_identity', return_value=A), patch.object(learning_routes, 'normalize', return_value=URL):
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as raised:
                await learning_routes.clear_workspace_subtitle(learning_routes.VisitRequest(url=URL), Request())
        self.assertEqual(409, raised.exception.status_code)
        self.assertFalse(learning.workspace(URL, A)['subtitle_cleared'])
        self.assertEqual('queued', job_store.get_job(task)['status'])

    async def test_explicit_acquisition_restores_cleared_subtitle_without_charging(self):
        self.save(text='共享字幕')
        learning.clear_subtitle(URL, A)
        with patch.object(learning_routes, 'require_identity', return_value=A), patch.object(learning_routes, 'normalize', return_value=URL):
            response = await learning_routes.prepare_subtitle(learning_routes.PrepareRequest(url=URL), Request())
        self.assertEqual(202, response.status_code)
        self.assertFalse(learning.workspace(URL, A)['subtitle_cleared'])
        self.assertEqual('共享字幕', learning.workspace(URL, A)['subtitle']['text'])
        with database.get_db() as conn:
            self.assertEqual(0, conn.execute('SELECT COUNT(*) FROM usage_logs').fetchone()[0])

    def test_admin_clear_overrides_other_identities_in_global_catalog(self):
        self.save(text='字幕')
        learning.record_visit(URL, B)
        learning.clear_subtitle(URL, A)
        admin = {**A, 'role': 'admin'}
        self.assertFalse(learned.content_by_bvid(admin, ['BV1state'])['BV1state'][1]['has_subtitle'])
        self.assertTrue(learned.content_by_bvid(B, ['BV1state'])['BV1state'][1]['has_subtitle'])
        store.upsert_video(self.creator, {'bvid': 'BV1state', 'title': '视频'})
        self.assertEqual(0, learned.video_counts(admin, [self.creator])[self.creator]['subtitle_count'])

    def test_migration_preserves_existing_rows_and_defaults(self):
        self.save(text='旧字幕')
        with database.get_db() as conn:
            conn.execute('ALTER TABLE user_history DROP COLUMN subtitle_cleared')
        database.init_db()
        self.assertFalse(learning.subtitle_is_cleared(URL, A))
        with database.get_db() as conn:
            self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM user_history').fetchone()[0])
