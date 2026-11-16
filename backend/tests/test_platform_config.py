from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core import platform_config as config
from core import bilibili
from core import bilibili_guard as guard
from api import admin_routes


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, '_PATH', tmp_path / 'platform.json')
    monkeypatch.setenv('BILIBILI_USE_ACCOUNT_COOKIE', 'true')
    monkeypatch.setattr(guard, 'STATE_PATH', tmp_path / 'guard.db')
    monkeypatch.setattr(guard, 'LIMITS', {'api': (0, ((3600, 10000),))})
    monkeypatch.delenv('BILIBILI_COOKIE', raising=False)
    monkeypatch.delenv('DOUYIN_COOKIE', raising=False)


def test_save_masks_secrets_and_blank_preserves(monkeypatch):
    config.save('bilibili', 'SESSDATA=private; bili_jct=token')
    assert 'private' not in str(config.get_public())
    config.save('bilibili', '')
    assert config.get_cookie('bilibili') == 'SESSDATA=private; bili_jct=token'
    assert config._PATH.stat().st_mode & 0o777 == 0o600
    monkeypatch.setenv('BILIBILI_COOKIE', 'SESSDATA=old-env')
    monkeypatch.setenv('BILIBILI_USE_ACCOUNT_COOKIE', 'false')
    assert bilibili.default_cookie() == ''
    monkeypatch.setenv('BILIBILI_USE_ACCOUNT_COOKIE', 'true')
    assert bilibili.default_cookie().startswith('SESSDATA=private')


def test_draft_validation_does_not_save(monkeypatch):
    config.save('bilibili', 'SESSDATA=saved')
    response = Mock(status_code=200)
    response.json.return_value = {'code': 0, 'data': {'isLogin': True}}
    monkeypatch.setattr(config.httpx, 'get', Mock(return_value=response))
    assert config.validate('bilibili', 'SESSDATA=draft')['valid']
    assert config.get_cookie('bilibili') == 'SESSDATA=saved'
    assert config.get_public()['platforms']['bilibili']['status'] == 'untested'
    assert config.validate('bilibili')['valid']
    assert config.get_public()['platforms']['bilibili']['status'] == 'valid'


@pytest.mark.parametrize('status,payload,expected', [
    (200, {'code': -101}, 'invalid'), (412, {}, 'unknown'),
    (200, {'code': -352}, 'unknown'),
])
def test_validation_distinguishes_login_and_risk(monkeypatch, status, payload, expected):
    response = Mock(status_code=status)
    response.json.return_value = payload
    monkeypatch.setattr(config.httpx, 'get', Mock(return_value=response))
    assert config.validate('bilibili', 'SESSDATA=test')['status'] == expected


def test_douyin_needs_authenticated_identity(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {'status_code': 0, 'user': {}}
    monkeypatch.setattr(config.httpx, 'get', Mock(return_value=response))
    assert config.validate('douyin', 'sessionid=test')['status'] == 'unknown'
    response.json.return_value = {'status_code': 0, 'user': {'uid': '123'}}
    assert config.validate('douyin', 'sessionid=test')['valid']


def test_network_failure_does_not_leak_credentials(monkeypatch):
    monkeypatch.setattr(config.httpx, 'get', Mock(side_effect=httpx.ReadTimeout('secret-cookie')))
    assert 'secret-cookie' not in str(config.validate('bilibili', 'SESSDATA=test'))


def test_cookiefile_rotates_after_update(monkeypatch):
    monkeypatch.setenv('BILIBILI_COOKIE_SCOPE', 'all')
    monkeypatch.setenv('BILIBILI_USE_ACCOUNT_COOKIE', 'true')
    config.save('bilibili', 'SESSDATA=one')
    first = bilibili._cookiefile()
    config.save('bilibili', 'SESSDATA=two')
    second = bilibili._cookiefile()
    assert first != second
    assert '\ttwo\n' in open(second).read()
    config.save('douyin', 'sessionid=three')
    opts = bilibili.ydl_opts_for('https://www.douyin.com/video/123')
    assert '.douyin.com' in open(opts['cookiefile']).read()


def test_invalid_input_and_permissions(monkeypatch):
    with pytest.raises(ValueError):
        config.save('bilibili', 'SESSDATA=x\nInjected=x')
    app = FastAPI()
    app.include_router(admin_routes.router)
    client = TestClient(app)
    monkeypatch.setattr('api.security.get_current_user', lambda request: None)
    assert client.get('/api/admin/platform-config').status_code == 403
    assert client.put('/api/admin/platform-config/bilibili', json={'cookie':'SESSDATA=x'}).status_code == 403
    monkeypatch.setattr('api.security.get_current_user', lambda request: {'role':'admin'})
    assert client.put('/api/admin/platform-config/bilibili', json={'cookie':'SESSDATA=x'}).status_code == 200
    assert client.put('/api/admin/platform-config/other', json={'cookie':'a=b'}).status_code == 400


def test_manual_validation_respects_access_protection(monkeypatch):
    guard.trip("测试暂停")
    request = Mock()
    monkeypatch.setattr(config.httpx, 'get', request)
    result = config.validate('bilibili', 'SESSDATA=manual')
    assert result['status'] == 'unknown'
    assert '暂时受限' in result['message']
    request.assert_not_called()


@pytest.mark.parametrize('cookie', ['SESSDATA=x\x00', 'SESSDATA=x\x7f'])
def test_cookie_control_characters_are_rejected(cookie):
    with pytest.raises(ValueError, match='单行'):
        config.save('bilibili', cookie)
