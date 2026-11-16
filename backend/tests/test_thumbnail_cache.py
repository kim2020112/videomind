from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from core import thumbnail_cache as cache


def test_cache_reuses_images_and_failure_is_not_saved():
    cache._entries.clear()
    fetch = Mock(return_value=SimpleNamespace(content=b'image', content_type='image/jpeg'))
    assert cache.cached_thumbnail('https://test/image', fetch).content == b'image'
    assert cache.cached_thumbnail('https://test/image', fetch).content == b'image'
    assert fetch.call_count == 1
    failure = Mock(side_effect=ValueError('blocked'))
    for _ in range(2):
        with pytest.raises(ValueError):
            cache.cached_thumbnail('https://test/fail', failure)
    assert failure.call_count == 2
