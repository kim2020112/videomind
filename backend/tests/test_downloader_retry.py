from contextlib import nullcontext
from unittest.mock import Mock

import pytest
from yt_dlp.networking.exceptions import HTTPError
from yt_dlp.utils import DownloadError

from core import downloader


@pytest.mark.parametrize('error', [
    RuntimeError('Login required'), RuntimeError('Fresh cookies are needed'),
    RuntimeError('Video not found'),
    *[HTTPError(Mock(status=code, reason='blocked')) for code in (401, 403, 404, 412, 429)],
])
def test_permanent_or_risk_error_is_not_retried(monkeypatch, tmp_path, error):
    wrapped = DownloadError('extraction failed', exc_info=(type(error), error, None))
    client = Mock()
    client.extract_info.side_effect = wrapped
    factory = Mock(return_value=nullcontext(client))
    monkeypatch.setattr(downloader, 'youtube_dl', factory)
    sleep = Mock()
    monkeypatch.setattr(downloader.time, 'sleep', sleep)
    with pytest.raises(RuntimeError):
        downloader.VideoDownloader(str(tmp_path)).parse_info('https://www.douyin.com/video/123')
    client.extract_info.assert_called_once()
    sleep.assert_not_called()
    assert factory.call_args.args[0]['extractor_retries'] == 0


def test_network_retries_have_one_bounded_owner(monkeypatch, tmp_path):
    client = Mock()
    client.extract_info.side_effect = TimeoutError('temporary timeout')
    monkeypatch.setattr(downloader, 'youtube_dl', lambda *args: nullcontext(client))
    sleep = Mock()
    monkeypatch.setattr(downloader.time, 'sleep', sleep)
    with pytest.raises(RuntimeError):
        downloader.VideoDownloader(str(tmp_path)).parse_info('https://www.youtube.com/watch?v=test')
    assert client.extract_info.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [2, 4]


def test_douyin_uses_original_extractor():
    from yt_dlp.extractor.tiktok import DouyinIE
    assert not getattr(DouyinIE, '_patched_amemv', False)
