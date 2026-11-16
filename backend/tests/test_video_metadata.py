from unittest.mock import Mock

import pytest

from core import video_metadata as metadata
from core.blogger import store, catalog
from core.bilibili_guard import trip


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(metadata, 'get_video_info_cache', lambda url: None)
    monkeypatch.setattr(store, 'get_video_by_bvid', lambda bvid: None)
    monkeypatch.setattr(store, 'list_pages', lambda video_id: [])


def test_synced_video_opens_while_webpage_is_blocked(setup, monkeypatch):
    trip('HTTP 412', 'video')
    monkeypatch.setattr(store, 'get_video_by_bvid', lambda bvid: {
        'id': 1, 'title': 'Synced title', 'duration': 10, 'description': 'description',
    })
    client = Mock(side_effect=AssertionError('No upstream calls for a synced video'))
    monkeypatch.setattr(catalog, 'BilibiliCatalogClient', client)
    downloader = Mock()
    info = metadata.learning_video_info('https://www.bilibili.com/video/BV1test', downloader)
    assert info.title == 'Synced title'
    downloader.parse_info.assert_not_called()
    client.assert_not_called()


def test_uncached_part_uses_metadata_api_and_exact_cid(setup, monkeypatch):
    client = Mock()
    client.parts.return_value = ({'title': 'Course', 'duration': 30}, [
        {'page': 1, 'cid': 101, 'part': 'First', 'duration': 10},
        {'page': 2, 'cid': 102, 'part': 'Second', 'duration': 20},
    ])
    monkeypatch.setattr(catalog, 'BilibiliCatalogClient', lambda: client)
    downloader = Mock()
    info = metadata.learning_video_info('https://www.bilibili.com/video/BV1test?p=2', downloader)
    assert info.duration == 20
    assert info.parts[1].cid == 102
    downloader.parse_info.assert_not_called()


def test_cached_metadata_requires_no_catalog_or_network(setup, monkeypatch):
    url = 'https://www.bilibili.com/video/BV1test'
    monkeypatch.setattr(metadata, 'get_video_info_cache', lambda url: {'title': 'Cached', 'webpage_url': url})
    monkeypatch.setattr(store, 'get_video_by_bvid', Mock(side_effect=AssertionError()))
    downloader = Mock()
    assert metadata.learning_video_info(url, downloader).title == 'Cached'
    downloader.parse_info.assert_not_called()


def test_metadata_api_refusal_is_not_followed_by_webpage_retry(setup, monkeypatch):
    from core.bilibili_guard import BilibiliAccessBlocked
    client = Mock()
    client.parts.side_effect = BilibiliAccessBlocked('limited')
    monkeypatch.setattr(catalog, 'BilibiliCatalogClient', lambda: client)
    downloader = Mock()
    with pytest.raises(BilibiliAccessBlocked):
        metadata.learning_video_info('https://www.bilibili.com/video/BV1test', downloader)
    downloader.parse_info.assert_not_called()
