import copy

import pytest

from core import ai_config
from core.text_client import ModelDiscoveryResult, TextClient, discover_model_list, model_list_candidates


@pytest.mark.parametrize(("api_format", "url", "expected"), [
    ("openai", "https://host.test", "https://host.test/v1"),
    ("openai", "https://host.test/custom/chat/completions", "https://host.test/custom/v1"),
    ("openai", "https://host.test/custom/v1/models/", "https://host.test/custom/v1"),
    ("anthropic", "https://host.test/custom/v1/messages", "https://host.test/custom"),
    ("anthropic", "https://host.test/custom///", "https://host.test/custom"),
])
def test_normalize_base_url(api_format, url, expected):
    assert ai_config.normalize_base_url(api_format, url) == expected


def test_refresh_preserves_missing_models(monkeypatch, tmp_path):
    original = copy.deepcopy(ai_config._store)
    monkeypatch.setattr(ai_config, "_CONFIG_PATH", tmp_path / "config.json")
    ai_config._store = {"version": 2, "connections": [{"id": "c1", "name": "gateway", "api_format": "openai",
        "api_key": "secret", "base_url": "https://host.test/v1", "models": [
            {"id": "old", "name": "old", "model": "old", "source": "manual", "status": "unverified"}]}],
        "active": {"connection_id": "c1", "model_id": "old"}}
    monkeypatch.setattr(ai_config.TextClient, "list_models", lambda _self, *_args: ModelDiscoveryResult([
        type("Model", (), {"model": "new", "name": "New"})()], "https://host.test/v1/models"))
    try:
        result = ai_config.refresh_models("c1")
        assert [(item["model"], item["discovery_status"]) for item in result["models"]] == [
            ("old", "not_returned"), ("new", "available")]
    finally:
        ai_config._store = original


def test_anthropic_discovery_includes_openai_sibling_paths():
    assert model_list_candidates("anthropic", "https://api.deepseek.com/anthropic") == [
        ("https://api.deepseek.com/anthropic/v1/models", "anthropic"),
        ("https://api.deepseek.com/models", "openai"),
        ("https://api.deepseek.com/v1/models", "openai"),
    ]


def test_anthropic_discovery_falls_back_after_404(monkeypatch):
    calls = []

    class Response:
        def __init__(self, status, payload=None):
            self.status_code = status
            self._payload = payload

        def json(self):
            return self._payload

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url, headers):
            calls.append((url, headers))
            if url.endswith("/anthropic/v1/models"):
                return Response(404)
            return Response(200, {"data": [{"id": "deepseek-chat"}]})

    monkeypatch.setattr("core.text_client.httpx.Client", Client)
    result = discover_model_list("anthropic", "secret", "https://api.deepseek.com/anthropic")

    assert result.url == "https://api.deepseek.com/models"
    assert [model.model for model in result.models] == ["deepseek-chat"]
    assert calls[0][1]["x-api-key"] == "secret"
    assert calls[1][1]["Authorization"] == "Bearer secret"


@pytest.mark.parametrize("reply", ["Your request was blocked.", "Access denied", "稍后重试"])
def test_model_rejects_gateway_error_text(reply):
    client = object.__new__(TextClient)
    client.generate = lambda *_args: reply

    with pytest.raises(ValueError, match="模型未按预期响应"):
        client.test_model("model-id")


@pytest.mark.parametrize("reply", ["OK", "ok", "OK.", "OK。"])
def test_model_accepts_clear_ok_reply(reply):
    client = object.__new__(TextClient)
    client.generate = lambda *_args: reply

    assert client.test_model("model-id")["success"] is True
