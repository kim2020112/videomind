import copy
import json

import pytest

from core import ai_config
from core.text_client import ModelDiscoveryResult


def model(model_id, *, source="discovered", discovery="available", test="untested"):
    return {
        "id": model_id,
        "name": model_id,
        "model": f"upstream-{model_id}",
        "source": source,
        "discovery_status": discovery,
        "test_status": test,
        "test_message": "previous result" if test != "untested" else "",
        "tested_at": "2026-07-16T10:00:00Z" if test != "untested" else "",
    }


def connection(connection_id, models, primary=None):
    return {
        "id": connection_id,
        "name": f"Connection {connection_id}",
        "api_format": "openai",
        "api_key": f"secret-{connection_id}",
        "base_url": f"https://{connection_id}.example.com/v1",
        "models_url": "",
        "discovery_url": "",
        "primary_model_id": primary or (models[0]["id"] if models else ""),
        "models": models,
    }


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    original = copy.deepcopy(ai_config._store)
    monkeypatch.setattr(ai_config, "_CONFIG_PATH", tmp_path / "ai-config.json")
    monkeypatch.setattr(ai_config.app_config, "AI_API_KEY", "")
    ai_config._store = {"version": 3, "connections": [],
                        "active": {"connection_id": "", "model_id": ""}}
    yield
    ai_config._store = original


def set_store(connections, connection_id="", model_id=""):
    ai_config._store = {
        "version": 3,
        "connections": copy.deepcopy(connections),
        "active": {"connection_id": connection_id, "model_id": model_id},
    }
    ai_config._store["providers"] = ai_config._store["connections"]


def test_v2_migration_adds_connection_primary_and_split_model_status_without_data_loss():
    legacy = {
        "version": 2,
        "connections": [
            {**connection("c1", [model("m1"), model("m2")]), "primary_model_id": "",
             "models": [
                 {"id": "m1", "name": "one", "model": "upstream-m1", "source": "manual", "status": "unverified"},
                 {"id": "m2", "name": "two", "model": "upstream-m2", "source": "discovered", "status": "available"},
             ]},
            {**connection("c2", [model("m3")]), "primary_model_id": "",
             "models": [{"id": "m3", "name": "three", "model": "upstream-m3", "source": "discovered", "status": "not_returned"}]},
        ],
        "active": {"connection_id": "c1", "model_id": "m2"},
    }
    ai_config._CONFIG_PATH.write_text(json.dumps(legacy), encoding="utf-8")

    ai_config._init()

    assert ai_config._store["version"] == 3
    assert ai_config._store["connections"][0]["primary_model_id"] == "m2"
    assert ai_config._store["connections"][1]["primary_model_id"] == "m3"
    assert ai_config._store["connections"][0]["api_key"] == "secret-c1"
    assert ai_config._store["connections"][0]["base_url"] == "https://c1.example.com/v1"
    assert ai_config._store["connections"][0]["models"][0]["discovery_status"] == "manual"
    assert ai_config._store["connections"][0]["models"][1]["discovery_status"] == "available"
    assert all(item["test_status"] == "untested" for item in ai_config._store["connections"][0]["models"])

    ai_config.switch_model("c1", "m2")
    persisted = json.loads(ai_config._CONFIG_PATH.read_text(encoding="utf-8"))
    assert persisted["version"] == 3
    assert "providers" not in persisted


def test_editing_inactive_connection_updates_its_primary_without_changing_active():
    set_store([connection("c1", [model("m1")]), connection("c2", [model("m2"), model("m3")])], "c1", "m1")

    ai_config.save_connection("Updated", "openai", "", "https://c2.example.com/v1",
                              [model("m2"), model("m3")], "m3", "c2")

    assert ai_config.get_active() == {"provider_id": "c1", "model_id": "m1"}
    assert ai_config._find_connection("c2")["primary_model_id"] == "m3"


def test_only_the_first_new_connection_is_automatically_activated():
    first = ai_config.save_connection("First", "openai", "key-1", "https://one.example.com",
                                      [{"name": "one", "model": "one", "source": "manual"}], "one")
    first_active = ai_config.get_active()
    second = ai_config.save_connection("Second", "openai", "key-2", "https://two.example.com",
                                       [{"name": "two", "model": "two", "source": "manual"}], "two")

    assert first_active == {"provider_id": first["id"], "model_id": first["primary_model_id"]}
    assert ai_config.get_active() == first_active
    assert second["primary_model_id"] != first["primary_model_id"]


def test_switch_atomically_updates_connection_primary_and_global_active():
    set_store([connection("c1", [model("m1"), model("m2")], "m1")], "c1", "m1")

    result = ai_config.switch_model("c1", "m2")

    assert result["active"] == {"connection_id": "c1", "model_id": "m2"}
    assert result["connection"]["primary_model_id"] == "m2"
    assert ai_config._find_connection("c1")["primary_model_id"] == "m2"


def test_failed_model_test_is_persisted(monkeypatch):
    set_store([connection("c1", [model("m1")])], "c1", "m1")
    monkeypatch.setattr(ai_config.TextClient, "test_model", lambda *_args: (_ for _ in ()).throw(ValueError("WAF blocked")))

    result = ai_config.test_model("c1", "m1")
    stored = ai_config._find_model(ai_config._find_connection("c1"), "m1")

    assert result["success"] is False
    assert stored["test_status"] == "failed"
    assert stored["test_message"] == "WAF blocked"
    assert stored["tested_at"].endswith("Z")


def test_refresh_changes_discovery_only_and_preserves_manual_models_and_test_results(monkeypatch):
    manual = model("manual", source="manual", discovery="manual", test="failed")
    discovered = model("known", discovery="not_returned", test="passed")
    set_store([connection("c1", [manual, discovered], "manual")], "c1", "manual")
    monkeypatch.setattr(ai_config.TextClient, "list_models", lambda *_args: ModelDiscoveryResult([
        type("Model", (), {"model": "upstream-known", "name": "Known now"})(),
        type("Model", (), {"model": "upstream-new", "name": "New"})(),
    ], "https://c1.example.com/v1/models"))

    result = ai_config.refresh_models("c1")
    by_id = {item["id"]: item for item in result["models"]}

    assert by_id["manual"]["discovery_status"] == "manual"
    assert by_id["manual"]["test_status"] == "failed"
    assert by_id["known"]["discovery_status"] == "available"
    assert by_id["known"]["test_status"] == "passed"
    assert result["primary_model_id"] == "manual"
    assert any(item["model"] == "upstream-new" for item in result["models"])


def test_delete_current_connection_falls_back_to_other_connections_primary_model():
    set_store([
        connection("c1", [model("m1")]),
        connection("c2", [model("m2"), model("m3")], "m3"),
    ], "c1", "m1")

    result = ai_config.delete_connection("c1")

    assert result["active"] == {"connection_id": "c2", "model_id": "m3"}
