"""管理员路由 — AI 服务商/模型配置管理。"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from api.auth_routes import get_current_user
from core import ai_config
from core.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin(request: Request) -> dict:
    user = get_current_user(request)
    if not user or user["role"] != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user


# ── 请求体 ──

class ProviderRequest(BaseModel):
    name: str
    provider: str
    api_key: str
    base_url: str


class ModelRequest(BaseModel):
    name: str
    model: str


class SwitchRequest(BaseModel):
    provider_id: str
    model_id: str


class TestRequest(BaseModel):
    api_key: str
    base_url: str
    model: str


# ── 查询 ──

@router.get("/ai-config")
async def get_config(request: Request):
    _require_admin(request)
    return {
        "providers": ai_config.get_all_providers(),
        "active": ai_config.get_active(),
    }


# ── 服务商 CRUD ──

@router.post("/ai-config/providers")
async def add_provider(req: ProviderRequest, request: Request):
    _require_admin(request)
    try:
        return ai_config.add_provider(req.name, req.provider, req.api_key, req.base_url)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/ai-config/providers/{provider_id}")
async def update_provider(provider_id: str, req: ProviderRequest, request: Request):
    _require_admin(request)
    try:
        return ai_config.update_provider(provider_id, req.name, req.provider, req.api_key, req.base_url)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/ai-config/providers/{provider_id}")
async def delete_provider(provider_id: str, request: Request):
    _require_admin(request)
    try:
        ai_config.delete_provider(provider_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok"}


@router.post("/ai-config/providers/{provider_id}/test")
async def test_provider(provider_id: str, request: Request):
    _require_admin(request)
    try:
        return ai_config.test_provider(provider_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── 模型 CRUD ──

@router.post("/ai-config/providers/{provider_id}/models")
async def add_model(provider_id: str, req: ModelRequest, request: Request):
    _require_admin(request)
    try:
        return ai_config.add_model(provider_id, req.name, req.model)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/ai-config/providers/{provider_id}/models/{model_id}")
async def update_model(provider_id: str, model_id: str, req: ModelRequest, request: Request):
    _require_admin(request)
    try:
        return ai_config.update_model(provider_id, model_id, req.name, req.model)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/ai-config/providers/{provider_id}/models/{model_id}")
async def delete_model(provider_id: str, model_id: str, request: Request):
    _require_admin(request)
    try:
        ai_config.delete_model(provider_id, model_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok"}


# ── 切换 ──

@router.post("/ai-config/switch")
async def switch_model(req: SwitchRequest, request: Request):
    _require_admin(request)
    try:
        ai_config.switch_model(req.provider_id, req.model_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok", "active": {"provider_id": req.provider_id, "model_id": req.model_id}}


# ── 测试连接（用传入参数） ──

@router.post("/ai-config/test")
async def test_config(req: TestRequest, request: Request):
    _require_admin(request)
    return ai_config.test_connection(req.api_key, req.base_url, req.model)
