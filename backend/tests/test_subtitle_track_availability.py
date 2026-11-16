from unittest.mock import Mock
import pytest
from core import summarizer
from core.bilibili_cache import _cacheable


def test_empty_preferred_track_does_not_hide_downloadable_track(monkeypatch):
    fetch = Mock(side_effect=[{'code':0,'data':{'subtitle':{'subtitles':[
        {'lan':'zh-Hans','subtitle_url':''},
        {'lan':'ai-zh','subtitle_url':'https://aisubtitle.hdslb.com/subtitle.json'},
    ]}}}, {'body':[{'from':0,'to':1,'content':'可下载中文字幕'}]}])
    monkeypatch.setattr(summarizer,'_fetch_bilibili_json',fetch)
    result=summarizer.extract_bilibili_subtitle_by_cid('BV1test',123)
    assert result['language']=='ai-zh'
    assert '可下载中文字幕' in result['text']
    assert fetch.call_count==2


def test_placeholder_metadata_is_not_cached_as_success():
    assert not _cacheable({'code':0,'data':{'subtitle':{'subtitles':[{'lan':'ai-zh','subtitle_url':''}]}}})
    assert not _cacheable({'code':0,'data':{'need_login_subtitle':True,'subtitle':{'subtitles':[]}}})


def test_empty_primary_track_can_use_existing_secondary_metadata(monkeypatch):
    track={'lan':'ai-zh','subtitle_url':'https://aisubtitle.hdslb.com/subtitle.json'}
    fetch=Mock(side_effect=[{'code':0,'data':{'subtitle':{'subtitles':[{'lan':'ai-zh','subtitle_url':''}]}}},
                           {'code':0,'data':{'subtitle':{'subtitles':[track]}}},
                           {'body':[{'from':0,'to':1,'content':'实际字幕'}]}])
    monkeypatch.setattr(summarizer,'_fetch_bilibili_json',fetch)
    result=summarizer.extract_bilibili_subtitle_by_cid('BV1test',123,aid=456)
    assert result['has_subtitle']
    assert fetch.call_count==3


def test_all_placeholder_tracks_report_specific_problem(monkeypatch):
    empty={'code':0,'data':{'subtitle':{'subtitles':[{'lan':'ai-zh','subtitle_url':''}]}}}
    monkeypatch.setattr(summarizer,'_fetch_bilibili_json',Mock(side_effect=[empty,empty]))
    with pytest.raises(RuntimeError,match='未提供可下载'):
        summarizer.extract_bilibili_subtitle_by_cid('BV1test',123,aid=456)


def test_mismatched_video_identity_stops_without_fallback(monkeypatch):
    fetch=Mock(return_value={'data':{'bvid':'BVother','cid':123}})
    monkeypatch.setattr(summarizer,'_fetch_bilibili_json',fetch)
    with pytest.raises(summarizer.SubtitleIdentityError):
        summarizer.extract_bilibili_subtitle_by_cid('BVexpected',123,456)
    assert fetch.call_count==1


def test_matching_envelope_with_foreign_subtitle_link_is_rejected(monkeypatch):
    fetch=Mock(return_value={'data':{'bvid':'BVexpected','cid':42924835613,'aid':117478143362727,
        'subtitle':{'subtitles':[{'lan':'ai-zh','subtitle_url':
          'https://aisubtitle.hdslb.com/bfs/ai_subtitle/prod/1132649649316122618215891885888184cfde86011242076306220b79'}]}}})
    monkeypatch.setattr(summarizer,'_fetch_bilibili_json',fetch)
    with pytest.raises(summarizer.SubtitleIdentityError,match='其他视频'):
        summarizer.extract_bilibili_subtitle_by_cid('BVexpected',42924835613)
    assert fetch.call_count==1


def test_subtitle_longer_than_video_is_rejected():
    with pytest.raises(summarizer.SubtitleIdentityError):
        summarizer.validate_subtitle_duration([{'end':1800}],516)
    summarizer.validate_subtitle_duration([{'end':516.2}],516)


def test_player_request_uses_signed_endpoint(monkeypatch):
    import httpx
    from urllib.parse import urlsplit, parse_qs
    from core.blogger.catalog import BilibiliCatalogClient
    monkeypatch.setattr(BilibiliCatalogClient,'ensure_wbi',lambda self:'test-key')
    response=httpx.Response(200,json={'code':0,'data':{}},request=httpx.Request('GET','https://api.bilibili.com'))
    fetch=Mock(return_value=response)
    monkeypatch.setattr(summarizer,'cached_get',fetch)
    summarizer._fetch_bilibili_json('https://api.bilibili.com/x/player/v2?bvid=BVtest&cid=123')
    url=urlsplit(fetch.call_args.args[0]);params=parse_qs(url.query)
    assert url.path=='/x/player/wbi/v2'
    assert params['bvid']==['BVtest'] and params['cid']==['123']
    assert params['wts'] and params['w_rid']
