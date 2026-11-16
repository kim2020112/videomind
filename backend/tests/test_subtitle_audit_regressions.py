import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import httpx
import pytest
from core import bilibili_cache as cache, summarizer
from core.models import VideoInfo
from core.pipeline import subtitle as pipeline
from core.subtitle_validation import validate_cached_subtitle


def test_conflicting_metadata_is_not_confirmed_absent(monkeypatch):
    monkeypatch.setattr(summarizer, '_fetch_bilibili_json', Mock(side_effect=[
        {'data': {'aid': 456, 'subtitle': {'subtitles': [{'subtitle_url': ''}]}}},
        {'data': {'subtitle': {'subtitles': []}}},
    ]))
    with pytest.raises(RuntimeError, match='未提供可下载'):
        summarizer.extract_bilibili_subtitle_by_cid('BVtest', 123, 456)


def test_parallel_identical_requests_share_result(monkeypatch):
    started, finish = threading.Event(), threading.Event()
    def upstream(*a, **kw):
        started.set()
        assert finish.wait(3)
        return httpx.Response(200, json={'code': 0, 'data': {}}, request=httpx.Request('GET', 'https://api.bilibili.com/test'))
    fetch = Mock(side_effect=upstream)
    monkeypatch.setattr(cache, 'guarded_get', fetch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.cached_get, 'https://api.bilibili.com/test')
        assert started.wait(2)
        second = pool.submit(cache.cached_get, 'https://api.bilibili.com/test')
        finish.set()
        assert first.result().json() == second.result().json()
    assert fetch.call_count == 1


def test_refresh_replaces_only_requested_resource(monkeypatch):
    fetch = Mock(side_effect=lambda url, **kw: httpx.Response(200, json={'code': 0, 'data': {'n': fetch.call_count}}, request=httpx.Request('GET', url)))
    monkeypatch.setattr(cache, 'guarded_get', fetch)
    a, b = 'https://api.bilibili.com/test?cid=1', 'https://api.bilibili.com/test?cid=2'
    old = cache.cached_get(a).json()
    other = cache.cached_get(b).json()
    with cache.refresh_responses():
        new = cache.cached_get(a).json()
    assert old != new
    assert cache.cached_get(a).json() == new
    assert cache.cached_get(b).json() == other
    assert fetch.call_count == 3


def test_cached_identity_and_selected_part_duration():
    info = {'duration': 1000, 'parts': [{'index': 2, 'cid': 22, 'duration': 30}]}
    sub = {'source': 'bilibili_cc', 'segments': [{'end': 80}], 'provenance': {'bvid': 'BVtest', 'cid': '22', 'version': 1}}
    with pytest.raises(summarizer.SubtitleIdentityError, match='时间轴'):
        validate_cached_subtitle('https://www.bilibili.com/video/BVtest?p=2', sub, info)
    sub['segments'] = [{'end': 20}]
    sub['provenance']['cid'] = '11'
    with pytest.raises(summarizer.SubtitleIdentityError, match='分 P'):
        validate_cached_subtitle('https://www.bilibili.com/video/BVtest?p=2', sub, info)


def test_subtitle_network_does_not_block_event_loop(monkeypatch):
    entered, finish = threading.Event(), threading.Event()
    monkeypatch.setattr(pipeline, 'get_subtitle_from_db', lambda u: None)
    def fetch(*a):
        entered.set()
        assert finish.wait(2)
        return {'has_subtitle': True, 'text': 'test', 'language': 'zh', 'segments': [{'end': 1}]}
    monkeypatch.setattr(pipeline, 'try_get_bilibili_cc_subtitle', fetch)
    async def run():
        info = VideoInfo(title='test', webpage_url='https://www.bilibili.com/video/BVtest', extractor='bilibili', duration=60)
        task = asyncio.create_task(pipeline.fetch_subtitle(info.webpage_url, info))
        while not entered.is_set():
            await asyncio.sleep(.001)
        # This runs while the upstream call is still blocked.
        finish.set()
        assert (await task)[0] == 'test'
    asyncio.run(run())


def test_invalid_identity_response_is_not_cached(monkeypatch):
    url = 'https://api.bilibili.com/x/player/wbi/v2?bvid=BVtest&cid=123'
    fetch = Mock(return_value=httpx.Response(200, json={'code': 0, 'data': {'bvid': 'BVother', 'cid': 123}}, request=httpx.Request('GET', url)))
    monkeypatch.setattr(cache, 'guarded_get', fetch)
    cache.cached_get(url)
    cache.cached_get(url)
    assert fetch.call_count == 2


def test_anonymous_signing_material_is_cached_only_for_nav(monkeypatch):
    payload = {'code': -101, 'data': {'wbi_img': {'img_url': 'test'}}}
    fetch = Mock(side_effect=lambda url, **kw: httpx.Response(200, json=payload, request=httpx.Request('GET', url)))
    monkeypatch.setattr(cache, 'guarded_get', fetch)
    for path in ('/x/web-interface/nav', '/x/player/wbi/v2'):
        for _ in range(2):
            cache.cached_get('https://api.bilibili.com' + path)
    assert fetch.call_count == 3


def test_old_request_cannot_overwrite_explicit_refresh(monkeypatch):
    old_started, finish_old = threading.Event(), threading.Event()
    url = 'https://api.bilibili.com/test?cid=9'
    def fetch(url, **kwargs):
        if threading.current_thread().name.startswith('old'):
            old_started.set()
            assert finish_old.wait(3)
            n = 'old'
        else:
            n = 'fresh'
        return httpx.Response(200, json={'code': 0, 'data': {'n': n}}, request=httpx.Request('GET', url))
    monkeypatch.setattr(cache, 'guarded_get', fetch)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='old') as pool:
        old = pool.submit(cache.cached_get, url)
        assert old_started.wait(2)
        with cache.refresh_responses():
            assert cache.cached_get(url).json()['data']['n'] == 'fresh'
        finish_old.set()
        assert old.result().json()['data']['n'] == 'old'
    assert cache.cached_get(url).json()['data']['n'] == 'fresh'


@pytest.mark.parametrize('end', [float('nan'), float('inf'), -1, 'invalid'])
def test_invalid_segment_times_fail_closed(end):
    with pytest.raises(summarizer.SubtitleIdentityError):
        summarizer.validate_subtitle_duration([{'start': 0, 'end': end}], 60)


def test_base_url_validates_first_part_not_total_video_duration():
    with pytest.raises(summarizer.SubtitleIdentityError, match='时间轴'):
        validate_cached_subtitle('https://www.bilibili.com/video/BVtest',
            {'source': 'bilibili_cc', 'segments': [{'start': 0, 'end': 80}]},
            {'duration': 1000, 'parts': [{'index': 1, 'duration': 30, 'cid': 1}]})


def test_legacy_text_only_subtitle_still_checks_time_evidence():
    with pytest.raises(summarizer.SubtitleIdentityError, match='时间轴'):
        validate_cached_subtitle('https://www.bilibili.com/video/BVtest',
            {'source': 'bilibili_cc', 'full_text': '[30:00] wrong', 'segments': []}, {'duration': 60})


@pytest.mark.parametrize('url', ['http://aisubtitle.hdslb.com/x', 'https://evil.example/x',
                                'https://aisubtitle.hdslb.com:8443/x', 'https://user@aisubtitle.hdslb.com/x'])
def test_subtitle_download_targets_are_restricted(url):
    from core.subtitle_identity import subtitle_link_identity
    with pytest.raises(summarizer.SubtitleIdentityError):
        subtitle_link_identity(url, 1, 2)


def test_malformed_success_is_not_treated_as_no_subtitle(monkeypatch):
    monkeypatch.setattr(summarizer, '_fetch_bilibili_json', Mock(return_value={'code': 0, 'data': {}}))
    assert summarizer.extract_bilibili_subtitle_by_cid('BVtest', 123) is None


def test_export_uses_validated_cache_and_srt_timestamps(monkeypatch):
    from core import subtitle_export, video_metadata
    import database
    info = VideoInfo(title='test', webpage_url='https://www.bilibili.com/video/BVtest', extractor='bilibili')
    monkeypatch.setattr(video_metadata, 'learning_video_info', lambda *a: info)
    async def fetch(*a, **kw):
        return 'test', 'bilibili_cc', 'ai-zh'
    monkeypatch.setattr(subtitle_export, 'fetch_subtitle', fetch)
    monkeypatch.setattr(database, 'get_subtitle_from_db', lambda u: {'source': 'bilibili_cc', 'full_text': 'test', 'segments': [{'start': 1.25, 'end': 3.5, 'text': 'test'}]})
    text, ext = subtitle_export.download_subtitle_content(info.webpage_url, 'zh', True, Mock())
    assert ext == 'srt'
    assert '00:00:01,250 --> 00:00:03,500' in text


def test_segment_content_tampering_is_rejected():
    import hashlib
    import json
    original = [{'start': 0, 'end': 1, 'text': 'original'}]
    proof = {'segments_sha256': hashlib.sha256(json.dumps(original, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}
    with pytest.raises(summarizer.SubtitleIdentityError, match='分段'):
        validate_cached_subtitle('https://www.bilibili.com/video/BVtest',
            {'source': 'bilibili_cc', 'full_text': 'original', 'segments': [{'start': 0, 'end': 1, 'text': 'wrong'}], 'provenance': proof})
