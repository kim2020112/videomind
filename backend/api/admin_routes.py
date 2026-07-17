"""Administrator endpoints for AI connections and models."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from api.security import require_admin
from core import ai_config

router = APIRouter(prefix="/api/admin", tags=["admin"])


class ModelSelection(BaseModel):
    id: str | None = None
    name: str
    model: str
    source: Literal["discovered", "manual"] = "discovered"
    discovery_status: Literal["available", "not_returned", "manual"] | None = None
    test_status: Literal["untested", "passed", "failed"] | None = None
    test_message: str = ""
    tested_at: str = ""
    # Accepted while version 2 clients are being migrated.
    status: Literal["available", "not_returned", "unverified"] | None = None


class ConnectionRequest(BaseModel):
    name: str
    api_format: Literal["openai", "anthropic"]
    api_key: str = ""
    base_url: str
    models_url: str = ""
    discovery_url: str = ""
    models: list[ModelSelection]
    primary_model: str = ""
    active_model: str = ""

    def selected_model(self) -> str:
        return self.primary_model or self.active_model


class DiscoverRequest(BaseModel):
    api_format: Literal["openai", "anthropic"]
    api_key: str
    base_url: str
    models_url: str = ""
    connection_id: str = ""


class SwitchRequest(BaseModel):
    connection_id: str
    model_id: str


def _bad_request(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.get("/ai-config")
async def get_config(request: Request):
    require_admin(request)
    active = ai_config.get_active()
    return {"version": 3, "connections": ai_config.get_all_connections(),
            "active": {"connection_id": active["provider_id"], "model_id": active["model_id"]}}


@router.post("/ai-config/discover")
async def discover(req: DiscoverRequest, request: Request):
    require_admin(request)
    return _bad_request(ai_config.discover_models, req.api_format, req.api_key, req.base_url,
                        req.models_url, req.connection_id)


@router.post("/ai-config/connections")
async def add_connection(req: ConnectionRequest, request: Request):
    require_admin(request)
    connection = _bad_request(ai_config.save_connection, req.name, req.api_format, req.api_key, req.base_url,
                              [item.model_dump() for item in req.models], req.selected_model(), None,
                              req.models_url, req.discovery_url)
    active = ai_config.get_active()
    return {"connection": connection,
            "active": {"connection_id": active["provider_id"], "model_id": active["model_id"]}}


@router.put("/ai-config/connections/{connection_id}")
async def update_connection(connection_id: str, req: ConnectionRequest, request: Request):
    require_admin(request)
    connection = _bad_request(ai_config.save_connection, req.name, req.api_format, req.api_key, req.base_url,
                              [item.model_dump() for item in req.models], req.selected_model(), connection_id,
                              req.models_url, req.discovery_url)
    active = ai_config.get_active()
    return {"connection": connection,
            "active": {"connection_id": active["provider_id"], "model_id": active["model_id"]}}


@router.delete("/ai-config/connections/{connection_id}")
async def delete_connection(connection_id: str, request: Request):
    require_admin(request)
    return _bad_request(ai_config.delete_connection, connection_id)


@router.post("/ai-config/connections/{connection_id}/refresh")
async def refresh_connection(connection_id: str, request: Request):
    require_admin(request)
    return _bad_request(ai_config.refresh_models, connection_id)


@router.post("/ai-config/connections/{connection_id}/models/{model_id}/test")
async def test_model(connection_id: str, model_id: str, request: Request):
    require_admin(request)
    return _bad_request(ai_config.test_model, connection_id, model_id)


@router.post("/ai-config/switch")
async def switch_model(req: SwitchRequest, request: Request):
    require_admin(request)
    return _bad_request(ai_config.switch_model, req.connection_id, req.model_id)
