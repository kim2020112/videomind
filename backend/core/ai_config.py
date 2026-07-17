"""Versioned runtime AI connection configuration with legacy migration."""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import config as app_config
from core.logging_config import get_logger
from core.text_client import TextClient

logger = get_logger(__name__)
_CONFIG_PATH = app_config.AI_CONFIG_PATH
_VERSION = 3
_store: dict = {"version": _VERSION, "connections": [], "active": {"connection_id": "", "model_id": ""}}


def _uid() -> str:
    return str(uuid.uuid4())[:8]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_base_url(api_format: str, value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Base URL 不能为空")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Base URL 必须是有效的 http(s) 地址")
    path = re.sub(r"/+", "/", parsed.path).rstrip("/")
    resources = ("/chat/completions", "/completions", "/messages", "/models")
    for suffix in resources:
        if path.endswith(suffix):
            path = path[:-len(suffix)].rstrip("/")
            break
    if api_format == "openai":
        if not path.endswith("/v1"):
            path = f"{path}/v1" if path else "/v1"
    elif api_format == "anthropic":
        if path.endswith("/v1"):
            path = path[:-3].rstrip("/")
    else:
        raise ValueError("兼容格式必须是 openai 或 anthropic")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _load_from_json() -> dict:
    if not _CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        logger.warning("加载 AI 配置文件失败: %s", error)
        return {}


def _save_to_json(data: dict):
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=str(_CONFIG_PATH.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, indent=2)
        os.replace(temporary, str(_CONFIG_PATH))
    except Exception:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def _model_status(item: dict, old: dict | None = None) -> tuple[str, str]:
    old = old or {}
    discovery = item.get("discovery_status")
    if discovery not in {"available", "not_returned", "manual"}:
        discovery = old.get("discovery_status")
    if discovery not in {"available", "not_returned", "manual"}:
        legacy = item.get("status") or old.get("status")
        if legacy == "not_returned":
            discovery = "not_returned"
        elif legacy == "available" and item.get("source") != "manual":
            discovery = "available"
        else:
            discovery = "manual"
    test = item.get("test_status")
    if test not in {"untested", "passed", "failed"}:
        test = old.get("test_status")
    if test not in {"untested", "passed", "failed"}:
        test = "untested"
    return discovery, test


def _normalize_model(item: dict, old: dict | None = None) -> dict:
    old = old or {}
    upstream = str(item.get("model", "")).strip()
    source = item.get("source") or old.get("source") or "discovered"
    discovery, test = _model_status({**item, "source": source}, old)
    incoming_test = item.get("test_status") in {"untested", "passed", "failed"}
    return {
        "id": old.get("id") or item.get("id") or _uid(),
        "name": str(item.get("name") or old.get("name") or upstream),
        "model": upstream,
        "source": source if source in {"discovered", "manual"} else "discovered",
        "discovery_status": discovery,
        "test_status": test,
        "test_message": str(item.get("test_message", "") if incoming_test else old.get("test_message", ""))[:200],
        "tested_at": str(item.get("tested_at", "") if incoming_test else old.get("tested_at", "")),
    }


def _normalize_connection(connection: dict, active: dict | None = None) -> dict:
    seen: set[str] = set()
    models = []
    for raw in connection.get("models", []):
        model = _normalize_model(raw)
        if model["model"] and model["model"] not in seen:
            seen.add(model["model"])
            models.append(model)
    primary = connection.get("primary_model_id", "")
    if not any(model["id"] == primary for model in models):
        active = active or {}
        if active.get("connection_id") == connection.get("id"):
            primary = active.get("model_id", "")
        if not any(model["id"] == primary for model in models):
            primary = models[0]["id"] if models else ""
    value = {
        "id": connection.get("id") or _uid(),
        "name": connection.get("name") or "连接",
        "api_format": connection.get("api_format") or "anthropic",
        "api_key": connection.get("api_key", ""),
        "base_url": connection.get("base_url", ""),
        "models_url": connection.get("models_url", ""),
        "discovery_url": connection.get("discovery_url", ""),
        "primary_model_id": primary,
        "models": models,
    }
    if connection.get("provider"):
        value["provider"] = connection["provider"]
    if connection.get("readonly"):
        value["readonly"] = True
    return value


def _legacy_to_connections(data: dict) -> tuple[list[dict], dict]:
    providers = data.get("providers")
    active = data.get("active", {})
    if providers is None and "models" in data:
        providers = []
        for item in data["models"]:
            match = next((provider for provider in providers if
                          (provider["api_key"], provider["base_url"]) ==
                          (item.get("api_key", ""), item.get("base_url", ""))), None)
            if match:
                match["models"].append(item)
            else:
                providers.append({"id": _uid(), "name": item.get("provider", "连接"),
                                  "api_key": item.get("api_key", ""), "base_url": item.get("base_url", ""),
                                  "models": [item]})
        legacy_active = data.get("active_id", "")
        for provider in providers:
            if any(model.get("id") == legacy_active for model in provider["models"]):
                active = {"provider_id": provider["id"], "model_id": legacy_active}
                break
    if providers is None and "model" in data:
        model_id, provider_id = _uid(), _uid()
        providers = [{"id": provider_id, "name": data.get("provider") or "默认连接",
                      "api_key": data.get("api_key", ""), "base_url": data.get("base_url", ""),
                      "models": [{"id": model_id, "name": data.get("model", ""),
                                  "model": data.get("model", ""), "source": "manual"}]}]
        active = {"provider_id": provider_id, "model_id": model_id}
    connections = []
    for provider in providers or []:
        base_url = provider.get("base_url", "")
        try:
            base_url = normalize_base_url("anthropic", base_url)
        except ValueError:
            pass
        connections.append({**provider, "api_format": provider.get("api_format", "anthropic"),
                            "base_url": base_url})
    return connections, {"connection_id": active.get("connection_id") or active.get("provider_id", ""),
                         "model_id": active.get("model_id", "")}


def _migrate_old_format(data: dict) -> dict:
    if data.get("version") in {2, 3} and "connections" in data:
        active = data.get("active", {})
        active = {"connection_id": active.get("connection_id") or active.get("provider_id", ""),
                  "model_id": active.get("model_id", "")}
        connections = data.get("connections", [])
    else:
        connections, active = _legacy_to_connections(data)
    migrated = {"version": _VERSION, "connections": [], "active": active}
    migrated["connections"] = [_normalize_connection(connection, active) for connection in connections]
    return migrated


def _connections(store=None):
    target = _store if store is None else store
    return target.get("connections", target.get("providers", []))


def _find_connection(connection_id: str, store=None):
    return next((item for item in _connections(store) if item["id"] == connection_id), None)


def _find_model(connection: dict | None, model_id: str):
    if not connection:
        return None
    return next((item for item in connection.get("models", []) if item["id"] == model_id), None)


def _normalize_active(store: dict):
    legacy = "connections" not in store
    active = store.setdefault("active", {})
    connection_id = active.get("connection_id") or active.get("provider_id", "")
    connection = _find_connection(connection_id, store)
    model = _find_model(connection, active.get("model_id", ""))
    if not model:
        connection = next((item for item in _connections(store) if item.get("models")), None)
        model = _find_model(connection, connection.get("primary_model_id", "")) if connection else None
        model = model or (connection["models"][0] if connection else None)
    id_key = "provider_id" if legacy else "connection_id"
    store["active"] = {id_key: connection["id"] if connection else "", "model_id": model["id"] if model else ""}
    return connection, model


def _init():
    global _store
    _store = _migrate_old_format(_load_from_json())
    _normalize_active(_store)
    _store["providers"] = _store["connections"]


def _commit(candidate: dict):
    global _store
    if "connections" not in candidate and "providers" in candidate:
        # Preserve the old in-memory shape for compatibility helpers and their callers.
        _normalize_active(candidate)
        _save_to_json(candidate)
        _store = candidate
        return
    candidate["version"] = _VERSION
    candidate["connections"] = [_normalize_connection(item, candidate.get("active"))
                                for item in candidate.get("connections", [])]
    _normalize_active(candidate)
    persisted = copy.deepcopy(candidate)
    persisted.pop("providers", None)
    _save_to_json(persisted)
    candidate["providers"] = candidate["connections"]
    _store = candidate


def _active_pair():
    return _normalize_active(_store)


def get_effective_api_format() -> str:
    connection, _ = _active_pair()
    return connection.get("api_format", "anthropic") if connection else getattr(app_config, "AI_API_FORMAT", "anthropic")


def get_effective_provider() -> str:
    connection, _ = _active_pair()
    return connection.get("provider", get_effective_api_format()) if connection else getattr(app_config, "AI_PROVIDER", get_effective_api_format())


def get_effective_api_key() -> str:
    connection, _ = _active_pair()
    return connection.get("api_key") if connection else app_config.AI_API_KEY


def get_effective_base_url() -> str:
    connection, _ = _active_pair()
    if connection:
        return connection["base_url"]
    try:
        return normalize_base_url(get_effective_api_format(), app_config.AI_BASE_URL)
    except ValueError:
        return app_config.AI_BASE_URL


def get_effective_model() -> str:
    _, model = _active_pair()
    return model.get("model") if model else app_config.AI_MODEL


def mask_api_key(key: str) -> str:
    return "****" if len(key or "") <= 4 else "*" * (len(key) - 4) + key[-4:]


def _public_connection(connection: dict) -> dict:
    keys = ("id", "name", "api_format", "base_url", "models_url", "discovery_url", "primary_model_id")
    return {**{key: connection.get(key, "") for key in keys},
            "api_key": mask_api_key(connection.get("api_key", "")),
            "models": [dict(model) for model in connection.get("models", [])],
            **({"readonly": True} if connection.get("readonly") else {})}


def get_all_connections() -> list[dict]:
    result = [_public_connection(item) for item in _connections()]
    connection, model = _active_pair()
    if not (connection and model) and app_config.AI_API_KEY:
        api_format = getattr(app_config, "AI_API_FORMAT", "anthropic")
        result.append(_public_connection({"id": "__env_default__", "name": ".env 默认连接",
            "api_format": api_format, "api_key": app_config.AI_API_KEY, "base_url": get_effective_base_url(),
            "readonly": True, "primary_model_id": "__env_model__", "models": [{"id": "__env_model__",
                "name": app_config.AI_MODEL, "model": app_config.AI_MODEL, "source": "manual",
                "discovery_status": "manual", "test_status": "untested", "test_message": "", "tested_at": ""}]}))
    return result


def get_all_providers():
    return [{**item, "provider": item["api_format"]} for item in get_all_connections()]


def get_active() -> dict:
    connection, model = _active_pair()
    if connection and model:
        return {"provider_id": connection["id"], "model_id": model["id"]}
    if app_config.AI_API_KEY:
        return {"provider_id": "__env_default__", "model_id": "__env_model__"}
    return {"provider_id": "", "model_id": ""}


def _active_public() -> dict:
    active = get_active()
    return {"connection_id": active["provider_id"], "model_id": active["model_id"]}


def discover_models(api_format: str, api_key: str, base_url: str, models_url: str = "",
                    connection_id: str = "") -> dict:
    connection = _find_connection(connection_id) if connection_id else None
    key = api_key.strip() or (connection.get("api_key", "") if connection else "")
    if not key:
        raise ValueError("API Key 不能为空")
    normalized = normalize_base_url(api_format, base_url)
    result = TextClient(api_format, key, normalized).list_models(models_url)
    return {"base_url": normalized, "models_url": models_url.strip(), "discovery_url": result.url,
            "models": [{"model": model.model, "name": model.name} for model in result.models]}


def save_connection(name: str, api_format: str, api_key: str, base_url: str, models: list[dict],
                    primary_model: str, connection_id: str | None = None, models_url: str = "",
                    discovery_url: str = "") -> dict:
    candidate = copy.deepcopy(_store)
    if "connections" not in candidate:
        candidate = _migrate_old_format(candidate)
    connection = _find_connection(connection_id, candidate) if connection_id else None
    if connection_id and not connection:
        raise ValueError("连接不存在")
    key = api_key.strip() or (connection.get("api_key", "") if connection else "")
    if not key:
        raise ValueError("API Key 不能为空")
    normalized = normalize_base_url(api_format, base_url)
    if not models:
        raise ValueError("至少保留一个模型")
    previous = {item["model"]: item for item in connection.get("models", [])} if connection else {}
    normalized_models = []
    seen = set()
    for item in models:
        upstream = str(item.get("model", "")).strip()
        if not upstream or upstream in seen:
            continue
        seen.add(upstream)
        normalized_models.append(_normalize_model(item, previous.get(upstream)))
    chosen = next((item for item in normalized_models if item["model"] == primary_model or
                   item["id"] == primary_model), None)
    if not chosen:
        raise ValueError("必须指定主力模型")
    value = {"id": connection_id or _uid(), "name": name.strip() or "未命名连接", "api_format": api_format,
             "api_key": key, "base_url": normalized, "models_url": models_url.strip(),
             "discovery_url": discovery_url.strip() or (connection.get("discovery_url", "") if connection else ""),
             "primary_model_id": chosen["id"], "models": normalized_models}
    was_empty = not any(item.get("models") for item in candidate.get("connections", []))
    if connection:
        candidate["connections"][candidate["connections"].index(connection)] = value
    else:
        candidate.setdefault("connections", []).append(value)
    if was_empty:
        candidate["active"] = {"connection_id": value["id"], "model_id": chosen["id"]}
    _commit(candidate)
    return _public_connection(_find_connection(value["id"]))


def refresh_models(connection_id: str) -> dict:
    candidate = copy.deepcopy(_store)
    connection = _find_connection(connection_id, candidate)
    if not connection:
        raise ValueError("连接不存在")
    result = TextClient(connection["api_format"], connection["api_key"], connection["base_url"]).list_models(
        connection.get("models_url", ""), connection.get("discovery_url", ""))
    connection["discovery_url"] = result.url
    returned = {item.model: item for item in result.models}
    for model in connection.get("models", []):
        if model["model"] in returned:
            model["discovery_status"] = "available"
            model["name"] = returned[model["model"]].name or model["name"]
        elif model.get("discovery_status") != "manual" or model.get("source") != "manual":
            model["discovery_status"] = "not_returned"
    known = {item["model"] for item in connection.get("models", [])}
    for upstream, item in returned.items():
        if upstream not in known:
            connection["models"].append(_normalize_model({"name": item.name, "model": upstream,
                "source": "discovered", "discovery_status": "available"}))
    _commit(candidate)
    return _public_connection(_find_connection(connection_id))


def test_model(connection_id: str, model_id: str) -> dict:
    if connection_id == "__env_default__":
        return test_connection(getattr(app_config, "AI_API_FORMAT", "anthropic"), app_config.AI_API_KEY,
                               app_config.AI_BASE_URL, app_config.AI_MODEL)
    connection = _find_connection(connection_id)
    if not connection:
        raise ValueError("连接不存在")
    model = _find_model(connection, model_id)
    if not model:
        raise ValueError("模型不存在")
    try:
        result = TextClient(connection["api_format"], connection["api_key"], connection["base_url"]).test_model(model["model"])
        success, message = result.get("success") is True, result.get("message", "模型响应正常")
    except Exception as error:
        success, message = False, str(error)[:200]
    candidate = copy.deepcopy(_store)
    stored = _find_model(_find_connection(connection_id, candidate), model_id)
    stored.update(test_status="passed" if success else "failed", test_message=message[:200], tested_at=_now_iso())
    _commit(candidate)
    return {"success": success, "message": message, "model": model["model"],
            "test_status": stored["test_status"], "tested_at": stored["tested_at"]}


def delete_connection(connection_id: str) -> dict:
    if not _find_connection(connection_id):
        raise ValueError("连接不存在")
    candidate = copy.deepcopy(_store)
    if "connections" not in candidate:
        key = "providers"
    else:
        key = "connections"
    candidate[key] = [item for item in _connections(candidate) if item["id"] != connection_id]
    _commit(candidate)
    return {"active": _active_public(), "connections": get_all_connections()}


def switch_model(connection_id: str, model_id: str) -> dict:
    connection = _find_connection(connection_id)
    if not connection or not _find_model(connection, model_id):
        raise ValueError(f"模型 {model_id} 不存在")
    candidate = copy.deepcopy(_store)
    stored_connection = _find_connection(connection_id, candidate)
    stored_connection["primary_model_id"] = model_id
    candidate["active"] = {"connection_id": connection_id, "model_id": model_id}
    _commit(candidate)
    return {"active": _active_public(), "connection": _public_connection(_find_connection(connection_id))}


def test_connection(api_format="anthropic", api_key=None, base_url=None, model=None) -> dict:
    api_key = get_effective_api_key() if api_key is None else api_key
    base_url = get_effective_base_url() if base_url is None else base_url
    model = get_effective_model() if model is None else model
    if not api_key or not base_url or not model:
        return {"success": False, "message": "API Key、Base URL 和模型均不能为空", "model": model or ""}
    try:
        return TextClient(api_format, api_key, normalize_base_url(api_format, base_url)).test_model(model)
    except Exception as error:
        return {"success": False, "message": str(error)[:200], "model": model}


# Legacy CRUD wrappers retained for callers during the API transition.
def add_provider(name, provider, api_key, base_url):
    return save_connection(name, "anthropic", api_key, base_url,
                           [{"model": app_config.AI_MODEL, "source": "manual"}], app_config.AI_MODEL)


def update_provider(provider_id, name, provider, api_key, base_url):
    current = _find_connection(provider_id)
    primary = current.get("primary_model_id") or current["models"][0]["id"]
    return save_connection(name, current.get("api_format", "anthropic"), api_key, base_url,
                           current["models"], primary, provider_id)


def delete_provider(provider_id):
    return delete_connection(provider_id)


def add_model(provider_id, name, model):
    connection = _find_connection(provider_id)
    models = connection["models"] + [{"name": name, "model": model, "source": "manual"}]
    saved = save_connection(connection["name"], connection.get("api_format", "anthropic"), "",
                            connection["base_url"], models, model, provider_id)
    return next(item for item in saved["models"] if item["model"] == model)


def update_model(provider_id, model_id, name, model):
    connection = _find_connection(provider_id)
    models = copy.deepcopy(connection["models"])
    target = next((item for item in models if item["id"] == model_id), None)
    if not target or not model.strip():
        raise ValueError("模型名称不能为空" if not model.strip() else "模型不存在")
    target.update(name=name.strip() or model.strip(), model=model.strip())
    primary = connection.get("primary_model_id") or models[0]["id"]
    saved = save_connection(connection["name"], connection.get("api_format", "anthropic"), "",
                            connection["base_url"], models, model if primary == model_id else primary, provider_id)
    return next(item for item in saved["models"] if item["id"] == model_id)


def delete_model(provider_id, model_id):
    connection = _find_connection(provider_id)
    models = [item for item in connection["models"] if item["id"] != model_id]
    if len(models) == len(connection["models"]):
        raise ValueError("模型不存在")
    if not models:
        candidate = copy.deepcopy(_store)
        stored = _find_connection(provider_id, candidate)
        stored["models"] = []
        stored["primary_model_id"] = ""
        _commit(candidate)
    else:
        save_connection(connection["name"], connection.get("api_format", "anthropic"), "",
                        connection["base_url"], models, models[0]["id"], provider_id)


def test_provider(provider_id):
    connection = _find_connection(provider_id)
    if not connection or not connection.get("models"):
        raise ValueError("连接没有可测试的模型")
    model_id = connection.get("primary_model_id") or connection["models"][0]["id"]
    return test_model(provider_id, model_id)


_init()
