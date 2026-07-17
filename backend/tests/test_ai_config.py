import copy
import json

import pytest

from core import ai_config


def provider(provider_id, models=None, **overrides):
    value = {
        "id": provider_id,
        "name": provider_id,
        "provider": f"type-{provider_id}",
        "api_key": f"key-{provider_id}",
        "base_url": f"https://{provider_id}.example.com",
        "models": models or [],
    }
    value.update(overrides)
    return value


def model(model_id, value=None):
    return {"id": model_id, "name": model_id, "model": value or f"model-{model_id}"}


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    original_store = copy.deepcopy(ai_config._store)
    monkeypatch.setattr(ai_config, "_CONFIG_PATH", tmp_path / "ai-config.json")
    monkeypatch.setattr(ai_config.app_config, "AI_PROVIDER", "env-provider")
    monkeypatch.setattr(ai_config.app_config, "AI_API_KEY", "env-api-key")
    monkeypatch.setattr(ai_config.app_config, "AI_BASE_URL", "https://env.example.com")
    monkeypatch.setattr(ai_config.app_config, "AI_MODEL", "env-model")
    ai_config._store = {"providers": [], "active": {"provider_id": "", "model_id": ""}}
    yield
    ai_config._store = original_store


def set_store(providers, provider_id="", model_id="", persist=True):
    ai_config._store = {
        "providers": copy.deepcopy(providers),
        "active": {"provider_id": provider_id, "model_id": model_id},
    }
    if persist:
        ai_config._save_to_json(ai_config._store)


def disk_store():
    return json.loads(ai_config._CONFIG_PATH.read_text(encoding="utf-8"))


def test_empty_model_update_keeps_memory_and_json_unchanged():
    set_store([provider("p1", [model("m1")])], "p1", "m1")
    before = copy.deepcopy(ai_config._store)

    with pytest.raises(ValueError, match="模型名称不能为空"):
        ai_config.update_model("p1", "m1", "changed", "   ")

    assert ai_config._store == before
    assert disk_store() == before


def test_empty_base_url_update_keeps_all_provider_fields_unchanged():
    set_store([provider("p1", [model("m1")])], "p1", "m1")
    before = copy.deepcopy(ai_config._store)

    with pytest.raises(ValueError, match="Base URL 不能为空"):
        ai_config.update_provider("p1", "changed", "changed-type", "new-key", "   ")

    assert ai_config._store == before
    assert disk_store() == before


def test_save_failure_rolls_back_entire_memory_store(monkeypatch):
    set_store([provider("p1", [model("m1")])], "p1", "m1")
    before = copy.deepcopy(ai_config._store)
    monkeypatch.setattr(ai_config, "_save_to_json", lambda _data: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(OSError, match="disk full"):
        ai_config.add_model("p1", "second", "model-2")

    assert ai_config._store == before


def test_deleting_active_model_selects_first_available_model_globally():
    providers = [provider("p1", [model("m1")]), provider("p2", [model("m2")])]
    set_store(providers, "p1", "m1")

    ai_config.delete_model("p1", "m1")

    assert ai_config.get_active() == {"provider_id": "p2", "model_id": "m2"}
    assert ai_config.get_effective_provider() == "type-p2"
    assert ai_config.get_effective_api_key() == "key-p2"
    assert ai_config.get_effective_base_url() == "https://p2.example.com"
    assert ai_config.get_effective_model() == "model-m2"


def test_deleting_active_provider_selects_first_available_model():
    providers = [provider("p1", [model("m1")]), provider("p2", [model("m2")])]
    set_store(providers, "p1", "m1")

    ai_config.delete_provider("p1")

    assert ai_config.get_active() == {"provider_id": "p2", "model_id": "m2"}
    assert disk_store()["active"] == {"provider_id": "p2", "model_id": "m2"}


def test_fallback_skips_provider_without_models():
    providers = [provider("empty"), provider("p2", [model("m2")])]
    set_store(providers, "missing", "missing")

    assert ai_config.get_active() == {"provider_id": "p2", "model_id": "m2"}
    assert ai_config.get_effective_model() == "model-m2"


@pytest.mark.parametrize(
    ("active_provider", "active_model"),
    [("missing", "m1"), ("p1", "missing")],
)
def test_stale_active_ids_are_normalized_on_read(active_provider, active_model):
    set_store([provider("p1", [model("m1")])], active_provider, active_model)

    assert ai_config.get_active() == {"provider_id": "p1", "model_id": "m1"}
    assert ai_config._store["active"] == {"provider_id": "p1", "model_id": "m1"}


def test_no_custom_models_uses_env_and_exposes_readonly_provider():
    set_store([provider("empty")], "empty", "")

    assert ai_config.get_active() == {
        "provider_id": "__env_default__",
        "model_id": "__env_model__",
    }
    assert ai_config.get_effective_provider() == "env-provider"
    assert ai_config.get_effective_api_key() == "env-api-key"
    assert ai_config.get_effective_base_url() == "https://env.example.com"
    assert ai_config.get_effective_model() == "env-model"
    providers = ai_config.get_all_providers()
    assert [item["id"] for item in providers] == ["empty", "__env_default__"]
    assert providers[-1]["readonly"] is True


def test_invalid_switch_keeps_memory_and_json_unchanged():
    set_store([provider("p1", [model("m1")])], "p1", "m1")
    before = copy.deepcopy(ai_config._store)

    with pytest.raises(ValueError, match="模型 missing 不存在"):
        ai_config.switch_model("p1", "missing")

    assert ai_config._store == before
    assert disk_store() == before


def test_current_multi_model_format_migration_normalizes_active():
    old = {
        "models": [
            {"id": "m1", "name": "one", "model": "model-1", "provider": "a", "api_key": "k1", "base_url": "u1"},
            {"id": "m2", "name": "two", "model": "model-2", "provider": "b", "api_key": "k2", "base_url": "u2"},
        ],
        "active_id": "missing",
    }
    ai_config._CONFIG_PATH.write_text(json.dumps(old), encoding="utf-8")

    ai_config._init()

    active = ai_config.get_active()
    assert active["provider_id"] == ai_config._store["providers"][0]["id"]
    assert active["model_id"] == "m1"
    assert json.loads(ai_config._CONFIG_PATH.read_text(encoding="utf-8")) == old


def test_single_model_format_migration_has_valid_active():
    old = {"provider": "legacy", "api_key": "key", "base_url": "url", "model": "legacy-model"}
    ai_config._CONFIG_PATH.write_text(json.dumps(old), encoding="utf-8")

    ai_config._init()

    active = ai_config.get_active()
    assert active["provider_id"] == ai_config._store["providers"][0]["id"]
    assert active["model_id"] == ai_config._store["providers"][0]["models"][0]["id"]
    assert json.loads(ai_config._CONFIG_PATH.read_text(encoding="utf-8")) == old
