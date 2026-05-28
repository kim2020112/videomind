"""运行时 AI 配置管理 — 服务商分组，支持多模型，JSON 文件持久化，热切换无需重启。"""

import json
import os
import tempfile
import uuid
from pathlib import Path

import anthropic

import config as app_config
from core.logging_config import get_logger

logger = get_logger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "data" / "ai_config.json"

# 新格式: {"providers": [{id, name, provider, api_key, base_url, models: [{id, name, model}]}], "active": {provider_id, model_id}}
_store: dict = {"providers": [], "active": {"provider_id": "", "model_id": ""}}


def _load_from_json() -> dict:
    if not _CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"加载 AI 配置文件失败: {e}")
        return {}


def _save_to_json(data: dict):
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(_CONFIG_PATH.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, str(_CONFIG_PATH))
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _migrate_old_format(data: dict) -> dict:
    """兼容旧格式，迁移到服务商分组格式。"""
    # 已经是新格式
    if "providers" in data:
        return data

    # 当前多模型格式 {models: [...], active_id}
    if "models" in data:
        providers = []
        for m in data["models"]:
            # 按 provider+api_key+base_url 分组
            matched = None
            for p in providers:
                if (p["provider"] == m.get("provider", "")
                        and p["api_key"] == m.get("api_key", "")
                        and p["base_url"] == m.get("base_url", "")):
                    matched = p
                    break
            if matched:
                matched["models"].append({
                    "id": m["id"],
                    "name": m.get("name", ""),
                    "model": m.get("model", ""),
                })
            else:
                providers.append({
                    "id": str(uuid.uuid4())[:8],
                    "name": m.get("provider", "服务商"),
                    "provider": m.get("provider", ""),
                    "api_key": m.get("api_key", ""),
                    "base_url": m.get("base_url", ""),
                    "models": [{
                        "id": m["id"],
                        "name": m.get("name", ""),
                        "model": m.get("model", ""),
                    }],
                })
        # 找到 active_id 对应的 provider_id 和 model_id
        active_id = data.get("active_id", "")
        provider_id = ""
        model_id = ""
        for p in providers:
            for mo in p["models"]:
                if mo["id"] == active_id:
                    provider_id = p["id"]
                    model_id = mo["id"]
                    break
        if not provider_id and providers:
            provider_id = providers[0]["id"]
            model_id = providers[0]["models"][0]["id"] if providers[0]["models"] else ""
        return {"providers": providers, "active": {"provider_id": provider_id, "model_id": model_id}}

    # 旧单配置格式 {model, provider, api_key, base_url}
    if "model" in data:
        pid = str(uuid.uuid4())[:8]
        mid = str(uuid.uuid4())[:8]
        return {
            "providers": [{
                "id": pid,
                "name": data.get("provider", "默认"),
                "provider": data.get("provider", ""),
                "api_key": data.get("api_key", ""),
                "base_url": data.get("base_url", ""),
                "models": [{"id": mid, "name": data.get("model", ""), "model": data.get("model", "")}],
            }],
            "active": {"provider_id": pid, "model_id": mid},
        }

    return data


def _init():
    global _store
    raw = _load_from_json()
    _store = _migrate_old_format(raw)
    if _store.get("providers"):
        provider, model = _get_active_pair()
        if provider and model:
            logger.info(f"已加载 AI 配置: {len(_store['providers'])} 个服务商, 当前: {model.get('model', '?')}")


def _find_provider(provider_id: str) -> dict | None:
    for p in _store.get("providers", []):
        if p["id"] == provider_id:
            return p
    return None


def _find_model_in_provider(provider: dict, model_id: str) -> dict | None:
    for m in provider.get("models", []):
        if m["id"] == model_id:
            return m
    return None


def _get_active_pair() -> tuple[dict | None, dict | None]:
    """返回 (provider, model) 激活对。"""
    active = _store.get("active", {})
    pid = active.get("provider_id", "")
    mid = active.get("model_id", "")
    provider = _find_provider(pid)
    if provider:
        model = _find_model_in_provider(provider, mid)
        if model:
            return provider, model
    # fallback 到第一个
    providers = _store.get("providers", [])
    if providers and providers[0].get("models"):
        return providers[0], providers[0]["models"][0]
    return None, None


# ── Getter（供 ai_client.py 调用，签名不变）──

def get_effective_provider() -> str:
    provider, _ = _get_active_pair()
    if provider and provider.get("provider"):
        return provider["provider"]
    return app_config.AI_PROVIDER


def get_effective_api_key() -> str:
    provider, _ = _get_active_pair()
    if provider and provider.get("api_key"):
        return provider["api_key"]
    return app_config.AI_API_KEY


def get_effective_base_url() -> str:
    provider, _ = _get_active_pair()
    if provider and provider.get("base_url"):
        return provider["base_url"]
    return app_config.AI_BASE_URL


def get_effective_model() -> str:
    _, model = _get_active_pair()
    if model and model.get("model"):
        return model["model"]
    return app_config.AI_MODEL


# ── 查询 ──

def get_all_providers() -> list[dict]:
    """返回所有服务商（api_key 脱敏），含 models 列表。"""
    result = []
    for p in _store.get("providers", []):
        result.append({
            "id": p["id"],
            "name": p.get("name", ""),
            "provider": p.get("provider", ""),
            "api_key": mask_api_key(p.get("api_key", "")),
            "base_url": p.get("base_url", ""),
            "models": [
                {"id": m["id"], "name": m.get("name", ""), "model": m.get("model", "")}
                for m in p.get("models", [])
            ],
        })
    return result


def get_active() -> dict:
    active = _store.get("active", {})
    return {"provider_id": active.get("provider_id", ""), "model_id": active.get("model_id", "")}


# ── 服务商 CRUD ──

def add_provider(name: str, provider: str, api_key: str, base_url: str) -> dict:
    if not api_key.strip():
        raise ValueError("API Key 不能为空")
    if not base_url.strip():
        raise ValueError("Base URL 不能为空")
    p = {
        "id": str(uuid.uuid4())[:8],
        "name": name.strip() or provider.strip(),
        "provider": provider.strip(),
        "api_key": api_key.strip(),
        "base_url": base_url.strip().rstrip("/"),
        "models": [],
    }
    _store.setdefault("providers", []).append(p)
    # 如果是第一个服务商且没有 active，设为激活
    if len(_store["providers"]) == 1 and not _store.get("active", {}).get("provider_id"):
        _store["active"] = {"provider_id": p["id"], "model_id": ""}
    _save_to_json(_store)
    logger.info(f"新增服务商: {p['name']}")
    return {"id": p["id"], "name": p["name"], "provider": p["provider"],
            "api_key": mask_api_key(p["api_key"]), "base_url": p["base_url"], "models": []}


def update_provider(provider_id: str, name: str, provider: str, api_key: str, base_url: str) -> dict:
    p = _find_provider(provider_id)
    if not p:
        raise ValueError(f"服务商 {provider_id} 不存在")
    p["name"] = name.strip() or provider.strip()
    p["provider"] = provider.strip()
    if api_key.strip():
        p["api_key"] = api_key.strip()
    p["base_url"] = base_url.strip().rstrip("/")
    if not p.get("api_key", "").strip():
        raise ValueError("API Key 不能为空")
    if not p.get("base_url", "").strip():
        raise ValueError("Base URL 不能为空")
    _save_to_json(_store)
    logger.info(f"更新服务商: {p['name']}")
    return {"id": p["id"], "name": p["name"], "provider": p["provider"],
            "api_key": mask_api_key(p["api_key"]), "base_url": p["base_url"],
            "models": [{"id": m["id"], "name": m["name"], "model": m["model"]} for m in p.get("models", [])]}


def delete_provider(provider_id: str):
    providers = _store.get("providers", [])
    p = _find_provider(provider_id)
    if not p:
        raise ValueError(f"服务商 {provider_id} 不存在")
    _store["providers"] = [x for x in providers if x["id"] != provider_id]
    # 如果删除的是当前激活的服务商，切换到第一个
    if _store.get("active", {}).get("provider_id") == provider_id:
        if _store["providers"]:
            first = _store["providers"][0]
            _store["active"] = {
                "provider_id": first["id"],
                "model_id": first["models"][0]["id"] if first.get("models") else "",
            }
        else:
            _store["active"] = {"provider_id": "", "model_id": ""}
    _save_to_json(_store)
    logger.info(f"删除服务商: {provider_id}")


# ── 模型 CRUD ──

def add_model(provider_id: str, name: str, model: str) -> dict:
    if not model.strip():
        raise ValueError("模型名称不能为空")
    p = _find_provider(provider_id)
    if not p:
        raise ValueError(f"服务商 {provider_id} 不存在")
    m = {"id": str(uuid.uuid4())[:8], "name": name.strip() or model.strip(), "model": model.strip()}
    p.setdefault("models", []).append(m)
    # 如果是该服务商第一个模型且当前没有激活模型，自动设为激活
    active = _store.get("active", {})
    if not active.get("model_id") and active.get("provider_id") == provider_id:
        active["model_id"] = m["id"]
    _save_to_json(_store)
    logger.info(f"新增模型: {m['name']} ({m['model']}) @ {p['name']}")
    return m


def update_model(provider_id: str, model_id: str, name: str, model: str) -> dict:
    p = _find_provider(provider_id)
    if not p:
        raise ValueError(f"服务商 {provider_id} 不存在")
    m = _find_model_in_provider(p, model_id)
    if not m:
        raise ValueError(f"模型 {model_id} 不存在于 {p['name']}")
    m["name"] = name.strip() or model.strip()
    m["model"] = model.strip()
    if not m["model"]:
        raise ValueError("模型名称不能为空")
    _save_to_json(_store)
    logger.info(f"更新模型: {m['name']} ({m['model']})")
    return m


def delete_model(provider_id: str, model_id: str):
    p = _find_provider(provider_id)
    if not p:
        raise ValueError(f"服务商 {provider_id} 不存在")
    before = len(p.get("models", []))
    p["models"] = [m for m in p.get("models", []) if m["id"] != model_id]
    if len(p["models"]) == before:
        raise ValueError(f"模型 {model_id} 不存在于 {p['name']}")
    # 如果删除的是当前激活模型，切换
    active = _store.get("active", {})
    if active.get("model_id") == model_id and active.get("provider_id") == provider_id:
        active["model_id"] = p["models"][0]["id"] if p["models"] else ""
    _save_to_json(_store)
    logger.info(f"删除模型: {model_id} @ {p['name']}")


def switch_model(provider_id: str, model_id: str):
    p = _find_provider(provider_id)
    if not p:
        raise ValueError(f"服务商 {provider_id} 不存在")
    m = _find_model_in_provider(p, model_id)
    if not m:
        raise ValueError(f"模型 {model_id} 不存在于 {p['name']}")
    _store["active"] = {"provider_id": provider_id, "model_id": model_id}
    _save_to_json(_store)
    logger.info(f"切换模型: {m['model']} @ {p['name']}")


# ── 工具 ──

def mask_api_key(key: str) -> str:
    if not key or len(key) <= 4:
        return "****"
    return "*" * (len(key) - 4) + key[-4:]


def test_connection(api_key: str = None, base_url: str = None, model: str = None) -> dict:
    """测试连通性。不传参数则用当前激活模型。"""
    api_key = api_key or get_effective_api_key()
    base_url = base_url or get_effective_base_url()
    model = model or get_effective_model()
    return _do_test(api_key, base_url, model)


def test_provider(provider_id: str) -> dict:
    """用指定服务商的 API Key 测试连通性（用第一个模型）。"""
    p = _find_provider(provider_id)
    if not p:
        raise ValueError(f"服务商 {provider_id} 不存在")
    model = p["models"][0]["model"] if p.get("models") else ""
    return _do_test(p["api_key"], p["base_url"], model)


def _do_test(api_key: str, base_url: str, model: str) -> dict:
    if not api_key:
        return {"success": False, "message": "未配置 API Key", "model": model}
    try:
        client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
        resp = client.messages.create(
            model=model,
            max_tokens=5,
            messages=[{"role": "user", "content": "Hi"}],
        )
        text = ""
        for block in resp.content:
            if hasattr(block, "text"):
                text = block.text.strip()
                break
        return {"success": True, "message": f"连接成功: {text}", "model": model}
    except Exception as e:
        return {"success": False, "message": str(e)[:200], "model": model}


# 模块加载时初始化
_init()
