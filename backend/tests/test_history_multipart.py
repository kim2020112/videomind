import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def run_backend(code: str, temp_root: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(BACKEND),
            "DB_PATH": str(temp_root / "db" / "knowledge.db"),
            "AI_CONFIG_PATH": str(temp_root / "data" / "ai_config.json"),
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


class MultipartHistoryTests(unittest.TestCase):
    def run_json(self, code: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_backend(code, Path(tmp))
            self.assertEqual(0, result.returncode, result.stderr)
            return json.loads(result.stdout.strip().splitlines()[-1])

    def test_ai_cache_read_preserves_platform_metadata(self):
        payload = self.run_json(
            """
import json
from core.cache import _max_prompt_version, get_cached, save_cache
from core.storage import initialize_storage

initialize_storage()
url = 'https://www.bilibili.com/video/BV1demo?p=20'
save_cache(
    url,
    result_json='{"result":{"summary":"cached"}}',
    platform='bilibili',
    prompt_version=_max_prompt_version(),
)
cached = get_cached(url)
print(json.dumps({'platform': cached.get('platform') if cached else None}))
"""
        )

        self.assertEqual("bilibili", payload["platform"])

    def test_part_titles_use_another_cached_part_when_first_url_has_no_metadata(self):
        payload = self.run_json(
            """
import json
from core.cache import _get_part_details_map, _get_total_parts_map, save_video_info_cache
from core.storage import initialize_storage

initialize_storage()
base_url = 'https://www.bilibili.com/video/BV1demo'
part_two_url = f'{base_url}?p=2'
save_video_info_cache(part_two_url, {
    'title': 'Demo course',
    'parts': [
        {'index': 1, 'title': 'Part one', 'duration': 60},
        {'index': 2, 'title': 'Part two', 'duration': 90},
    ],
})
details = _get_part_details_map([base_url, part_two_url])
totals = _get_total_parts_map([base_url, part_two_url])
print(json.dumps({
    'part_one': details.get(base_url, {}).get(1, {}).get('title'),
    'part_two': details.get(part_two_url, {}).get(2, {}).get('title'),
    'total_parts': totals.get(base_url),
}))
"""
        )
        self.assertEqual("Part one", payload["part_one"])
        self.assertEqual("Part two", payload["part_two"])
        self.assertEqual(2, payload["total_parts"])

    def test_video_info_cache_keeps_parts_separate_when_fingerprint_is_shared(self):
        payload = self.run_json(
            """
import json
from core.cache import save_video_info_cache
from core.storage import initialize_storage
from database import get_db

initialize_storage()
base_url = 'https://www.bilibili.com/video/BV1demo'
part_twenty_url = f'{base_url}?p=20'
part_twenty_one_url = f'{base_url}?p=21'
shared_fingerprint = 'BiliBili:BV1demo'

save_video_info_cache(
    part_twenty_one_url,
    {'id': 'BV1demo_p21', 'title': 'Part 21'},
    fingerprint=shared_fingerprint,
)
save_video_info_cache(
    part_twenty_url,
    {'id': 'BV1demo_p20', 'title': 'Part 20 from parse'},
)

error = None
try:
    save_video_info_cache(
        part_twenty_url,
        {'id': 'BV1demo_p20', 'title': 'Part 20 refreshed'},
        fingerprint=shared_fingerprint,
    )
except Exception as exc:
    error = str(exc)

with get_db() as conn:
    rows = conn.execute(
        "SELECT url, fingerprint, title FROM video_info_cache "
        "WHERE url IN (?, ?) ORDER BY url",
        (part_twenty_url, part_twenty_one_url),
    ).fetchall()

print(json.dumps({
    'error': error,
    'rows': [dict(row) for row in rows],
}))
"""
        )

        self.assertIsNone(payload["error"])
        self.assertEqual(
            [
                {
                    "url": "https://www.bilibili.com/video/BV1demo?p=20",
                    "fingerprint": "BiliBili:BV1demo",
                    "title": "Part 20 refreshed",
                },
                {
                    "url": "https://www.bilibili.com/video/BV1demo?p=21",
                    "fingerprint": "BiliBili:BV1demo",
                    "title": "Part 21",
                },
            ],
            payload["rows"],
        )

    def test_ai_cache_does_not_map_multiple_parts_to_implicit_part_one(self):
        payload = self.run_json(
            """
import json
from core.auth import add_user_history
from core.cache import _max_prompt_version, _url_hash, get_cached, save_cache
from core.storage import initialize_storage
from database import get_db

initialize_storage()
base_url = 'https://www.bilibili.com/video/BV1demo'
part_twenty_url = f'{base_url}?p=20'
part_twenty_one_url = f'{base_url}?p=21'
shared_fingerprint = 'BiliBili:BV1demo'
version = _max_prompt_version()

for url, title in ((part_twenty_url, 'Part 20'), (part_twenty_one_url, 'Part 21')):
    save_cache(url, video_title=title, result_json='{"result":{"summary":"cached"}}',
               fingerprint=shared_fingerprint, prompt_version=version)
    add_user_history(user_id=7, url_hash=_url_hash(url), url=url, status='done')

error = None
cached = None
try:
    cached = get_cached(base_url, fingerprint=shared_fingerprint)
except Exception as exc:
    error = str(exc)

with get_db() as conn:
    cache_urls = [row['url'] for row in conn.execute(
        'SELECT url FROM ai_cache ORDER BY url'
    ).fetchall()]
    history_urls = [row['url'] for row in conn.execute(
        'SELECT url FROM user_history ORDER BY url'
    ).fetchall()]

print(json.dumps({
    'error': error,
    'cached_url': cached.get('url') if cached else None,
    'cache_urls': cache_urls,
    'history_urls': history_urls,
}))
"""
        )

        self.assertIsNone(payload["error"])
        self.assertIsNone(payload["cached_url"])
        self.assertEqual(
            [
                "https://www.bilibili.com/video/BV1demo?p=20",
                "https://www.bilibili.com/video/BV1demo?p=21",
            ],
            payload["cache_urls"],
        )
        self.assertEqual(payload["cache_urls"], payload["history_urls"])

    def test_ai_cache_does_not_replay_a_single_part_for_implicit_part_one(self):
        payload = self.run_json(
            """
import json
from core.cache import _max_prompt_version, get_cached, save_cache
from core.storage import initialize_storage

initialize_storage()
base_url = 'https://www.bilibili.com/video/BV1demo'
part_twenty_url = f'{base_url}?p=20'
shared_fingerprint = 'BiliBili:BV1demo'
save_cache(
    part_twenty_url,
    video_title='Part 20',
    result_json='{"result":{"summary":"part twenty"}}',
    fingerprint=shared_fingerprint,
    prompt_version=_max_prompt_version(),
)
cached = get_cached(base_url, fingerprint=shared_fingerprint)
print(json.dumps({'cached_url': cached.get('url') if cached else None}))
"""
        )

        self.assertIsNone(payload["cached_url"])

    def test_whisper_cache_keeps_shared_fingerprint_parts_separate(self):
        payload = self.run_json(
            """
import json
from core.cache import get_whisper_cache, save_whisper_cache
from core.storage import initialize_storage
from database import get_db

initialize_storage()
base_url = 'https://www.bilibili.com/video/BV1demo'
part_twenty_url = f'{base_url}?p=20'
part_twenty_one_url = f'{base_url}?p=21'
shared_fingerprint = 'BiliBili:BV1demo'
save_whisper_cache(part_twenty_url, 'part twenty text', fingerprint=shared_fingerprint)
save_whisper_cache(part_twenty_one_url, 'part twenty-one text', fingerprint=shared_fingerprint)

with get_db() as conn:
    rows = [dict(row) for row in conn.execute(
        'SELECT url, subtitle_text FROM whisper_cache ORDER BY url'
    ).fetchall()]

print(json.dumps({
    'rows': rows,
    'base': get_whisper_cache(base_url, fingerprint=shared_fingerprint),
    'part_twenty': get_whisper_cache(part_twenty_url, fingerprint=shared_fingerprint),
    'part_twenty_one': get_whisper_cache(part_twenty_one_url, fingerprint=shared_fingerprint),
}))
"""
        )

        self.assertEqual(
            [
                {
                    "url": "https://www.bilibili.com/video/BV1demo?p=20",
                    "subtitle_text": "part twenty text",
                },
                {
                    "url": "https://www.bilibili.com/video/BV1demo?p=21",
                    "subtitle_text": "part twenty-one text",
                },
            ],
            payload["rows"],
        )
        self.assertIsNone(payload["base"])
        self.assertEqual("part twenty text", payload["part_twenty"])
        self.assertEqual("part twenty-one text", payload["part_twenty_one"])

    def test_video_info_fingerprint_does_not_replay_a_part_for_implicit_part_one(self):
        payload = self.run_json(
            """
import json
from core.cache import get_video_info_cache, save_video_info_cache
from core.storage import initialize_storage

initialize_storage()
base_url = 'https://www.bilibili.com/video/BV1demo'
part_twenty_url = f'{base_url}?p=20'
shared_fingerprint = 'BiliBili:BV1demo'
save_video_info_cache(
    part_twenty_url,
    {'id': 'BV1demo_p20', 'title': 'Part 20'},
    fingerprint=shared_fingerprint,
)
cached = get_video_info_cache(base_url, fingerprint=shared_fingerprint)
print(json.dumps({'title': cached.get('title') if cached else None}))
"""
        )

        self.assertIsNone(payload["title"])

    def test_deleting_one_part_cache_preserves_sibling_parts(self):
        payload = self.run_json(
            """
import json
from core.cache import delete_cache, delete_whisper_cache, save_cache, save_whisper_cache
from core.storage import initialize_storage
from database import get_db

initialize_storage()
base_url = 'https://www.bilibili.com/video/BV1demo'
part_twenty_url = f'{base_url}?p=20'
part_twenty_one_url = f'{base_url}?p=21'
shared_fingerprint = 'BiliBili:BV1demo'
for url in (part_twenty_url, part_twenty_one_url):
    save_cache(url, result_json='{"result":{"summary":"cached"}}', fingerprint=shared_fingerprint)
    save_whisper_cache(url, f'text for {url}', fingerprint=shared_fingerprint)

delete_cache(part_twenty_url, fingerprint=shared_fingerprint)
delete_whisper_cache(part_twenty_url, fingerprint=shared_fingerprint)
with get_db() as conn:
    ai_urls = [row['url'] for row in conn.execute('SELECT url FROM ai_cache ORDER BY url').fetchall()]
    whisper_urls = [row['url'] for row in conn.execute('SELECT url FROM whisper_cache ORDER BY url').fetchall()]
print(json.dumps({'ai_urls': ai_urls, 'whisper_urls': whisper_urls}))
"""
        )

        expected = ["https://www.bilibili.com/video/BV1demo?p=21"]
        self.assertEqual(expected, payload["ai_urls"])
        self.assertEqual(expected, payload["whisper_urls"])

    def test_admin_history_deduplicates_same_part_saved_by_guest_and_user(self):
        payload = self.run_json(
            """
import json
from database import get_db
from core.auth import add_user_history
from core.cache import _url_hash, list_history_enhanced, save_video_info_cache
from core.storage import initialize_storage

initialize_storage()
base_url = 'https://www.bilibili.com/video/BV1demo'
part_two_url = f'{base_url}?p=2'
save_video_info_cache(part_two_url, {
    'title': 'Demo course',
    'parts': [
        {'index': 1, 'title': 'Part one', 'duration': 60},
        {'index': 2, 'title': 'Part two', 'duration': 90},
    ],
})
add_user_history(guest_id='guest-a', url_hash=_url_hash(base_url), url=base_url, title='Demo course')
add_user_history(user_id=7, url_hash=_url_hash(base_url), url=base_url, title='Demo course')
add_user_history(user_id=7, url_hash=_url_hash(part_two_url), url=part_two_url, title='Demo course')
with get_db() as conn:
    conn.execute("UPDATE user_history SET created_at = '2024-01-01 00:00:00' WHERE guest_id = 'guest-a'")
item = list_history_enhanced(role='admin', limit=20)['items'][0]
print(json.dumps({
    'part_indexes': [part['part_index'] for part in item['parts']],
    'part_titles': [part['part_title'] for part in item['parts']],
}))
"""
        )
        self.assertEqual([1, 2], payload["part_indexes"])
        self.assertEqual(["Part one", "Part two"], payload["part_titles"])

    def test_learned_parts_require_current_user_done_history_and_ai_cache(self):
        payload = self.run_json(
            """
import json
from core.auth import add_user_history
from core.cache import _url_hash, get_learned_part_indexes, save_cache
from core.storage import initialize_storage
from database import get_db

initialize_storage()
base_url = 'https://www.bilibili.com/video/BV1demo'
urls = {index: f'{base_url}?p={index}' for index in range(1, 6)}

for index in (1, 2, 4, 5):
    target = urls[index] if index != 5 else 'https://www.bilibili.com/video/BV1other?p=5'
    save_cache(target, result_json='{"result":{"summary":"cached"}}')

add_user_history(user_id=7, url_hash=_url_hash(urls[1]), url=urls[1], status='done')
add_user_history(user_id=7, url_hash=_url_hash(urls[2]), url=urls[2], status='failed')
add_user_history(user_id=7, url_hash=_url_hash(urls[3]), url=urls[3], status='done')
add_user_history(user_id=8, url_hash=_url_hash(urls[4]), url=urls[4], status='done')
other_url = 'https://www.bilibili.com/video/BV1other?p=5'
add_user_history(user_id=7, url_hash=_url_hash(other_url), url=other_url, status='done')

print(json.dumps({
    'user_7': sorted(get_learned_part_indexes(base_url, user_id=7)),
    'user_8': sorted(get_learned_part_indexes(base_url, user_id=8)),
}))
"""
        )
        self.assertEqual([1], payload["user_7"])
        self.assertEqual([4], payload["user_8"])

    def test_successful_retry_promotes_existing_failed_history(self):
        payload = self.run_json(
            """
import json
from core.auth import add_user_history
from core.cache import _url_hash
from core.storage import initialize_storage
from database import get_db

initialize_storage()
url = 'https://www.bilibili.com/video/BV1demo?p=20'
url_hash = _url_hash(url)
add_user_history(user_id=7, url_hash=url_hash, url=url, status='failed')
add_user_history(user_id=7, url_hash=url_hash, url=url, status='done')

with get_db() as conn:
    rows = conn.execute(
        "SELECT status FROM user_history WHERE user_id = ? AND url_hash = ?",
        (7, url_hash),
    ).fetchall()

print(json.dumps({
    'count': len(rows),
    'status': rows[0]['status'],
}))
"""
        )

        self.assertEqual(1, payload["count"])
        self.assertEqual("done", payload["status"])

    def test_successful_retry_promotes_existing_failed_guest_history(self):
        payload = self.run_json(
            """
import json
from core.auth import add_user_history
from core.cache import _url_hash
from core.storage import initialize_storage
from database import get_db

initialize_storage()
url = 'https://www.bilibili.com/video/BV1demo?p=20'
url_hash = _url_hash(url)
add_user_history(guest_id='guest-a', url_hash=url_hash, url=url, status='failed')
add_user_history(guest_id='guest-a', url_hash=url_hash, url=url, status='done')

with get_db() as conn:
    rows = conn.execute(
        "SELECT status FROM user_history WHERE guest_id = ? AND url_hash = ?",
        ('guest-a', url_hash),
    ).fetchall()

print(json.dumps({
    'count': len(rows),
    'status': rows[0]['status'],
}))
"""
        )

        self.assertEqual(1, payload["count"])
        self.assertEqual("done", payload["status"])

class MultipartParseStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_parse_marks_learned_parts_for_current_identity(self):
        from api import routes
        from core.models import ParseRequest, VideoInfo, VideoPart

        url = "https://www.bilibili.com/video/BV1demo"
        info = VideoInfo(
            title="Demo",
            webpage_url=url,
            extractor="BiliBili",
            parts=[
                VideoPart(index=1, title="Part one"),
                VideoPart(index=2, title="Part two"),
            ],
        )

        with (
            patch.object(routes, "require_identity", return_value={"user_id": 7, "guest_id": None, "role": "user"}),
            patch.object(routes, "extract_url", return_value=url),
            patch.object(routes, "ensure_public_http_url"),
            patch.object(routes.downloader, "parse_info", return_value=info),
            patch.object(routes, "save_video_info_cache"),
            patch.object(routes, "get_learned_part_indexes", return_value={2}),
        ):
            parsed = await routes.parse_video(ParseRequest(url=url), object())

        self.assertFalse(parsed.parts[0].is_cached)
        self.assertTrue(parsed.parts[1].is_cached)

    async def test_parse_uses_canonical_url_for_cache_and_learned_parts(self):
        from api import routes
        from core.models import ParseRequest, VideoInfo, VideoPart

        short_url = "https://B23.TV/demo"
        canonical_url = "https://www.bilibili.com/video/BV1demo?p=20"
        info = VideoInfo(
            title="Demo",
            webpage_url=canonical_url,
            id="BV1demo_p20",
            extractor="BiliBili",
            parts=[VideoPart(index=20, title="Part twenty")],
        )

        with (
            patch.object(routes, "require_identity", return_value={"user_id": 7, "guest_id": None, "role": "user"}),
            patch.object(routes, "extract_url", return_value=short_url),
            patch.object(routes, "ensure_public_http_url"),
            patch.object(routes.downloader, "parse_info", return_value=info),
            patch.object(routes, "save_video_info_cache") as save_info,
            patch.object(routes, "get_learned_part_indexes", return_value={20}) as learned_parts,
        ):
            parsed = await routes.parse_video(ParseRequest(url=short_url), object())

        save_info.assert_called_once_with(canonical_url, info)
        learned_parts.assert_called_once_with(
            canonical_url,
            user_id=7,
            guest_id=None,
            role="user",
        )
        self.assertEqual(canonical_url, parsed.webpage_url)
        self.assertTrue(parsed.parts[0].is_cached)


if __name__ == "__main__":
    unittest.main()
