"""博主订阅与投稿目录 API。目录按身份隔离（user/guest 各自的订阅列表）。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from api.security import require_identity
from core.blogger import store, sync
from core.blogger import batches as batches_mod
from core.blogger import learned as learned_mod
from core.blogger.catalog import CatalogError, BilibiliCatalogClient, parse_creator_input
from core.logging_config import get_logger

logger = get_logger("blogger.routes")
from core.cache import _extract_part_index, _extract_video_key
from core.content_state import content_state

router = APIRouter(prefix="/api", tags=["bloggers"])


def _identity_owner(identity: dict) -> dict:
    return {"user_id": identity.get("user_id"), "guest_id": identity.get("guest_id")}


def _sub_or_404(sub_id: int, identity: dict) -> dict:
    sub = store.get_sub(sub_id, identity)
    if not sub:
        raise HTTPException(status_code=404, detail="博主订阅不存在")
    return sub


def _part_url(bvid: str, page: int) -> str:
    return f"https://www.bilibili.com/video/{bvid}" + (f"?p={page}" if page and page > 1 else "")


def _learned_parts_map(identity: dict, bvids: list[str]) -> dict[str, set[int]]:
    """bvid → 已学分 P 序号集合（条件统一走 learned 模块）。"""
    from core.cache import _ensure_table
    _ensure_table()  # ai_cache 为懒建表
    wanted = set(bvids)
    return {
        bvid: parts
        for bvid, parts in learned_mod.learned_bvid_sets(identity).items()
        if bvid in wanted
    }


def _catalog_error_status(error: CatalogError) -> int:
    return {
        "invalid_input": 400,
        "unavailable": 400,
        "rate_limit": 429,
        "login": 502,
    }.get(error.code, 502)


@router.post("/bloggers/preview")
async def preview_blogger(request: Request):
    """解析并预览 UP 主资料，不写库；重复订阅时给出提示标记。"""
    identity = require_identity(request)
    body = await request.json()
    raw_input = (body or {}).get("input") or ""
    try:
        uid = await asyncio.to_thread(parse_creator_input, raw_input)
    except CatalogError as error:
        raise HTTPException(status_code=_catalog_error_status(error), detail=str(error))
    client = BilibiliCatalogClient()
    try:
        profile = await asyncio.to_thread(client.profile, uid)
    except CatalogError as error:
        raise HTTPException(status_code=_catalog_error_status(error), detail=str(error))
    existing = store.find_sub_by_uid(_identity_owner(identity), uid)
    return {
        "profile": {"uid": uid, **profile},
        "already_subscribed": existing is not None,
        "sub": store.get_sub(existing["id"], identity) if existing else None,
    }


@router.post("/bloggers")
async def add_blogger(request: Request):
    identity = require_identity(request)
    body = await request.json()
    raw_input = (body or {}).get("input") or ""
    try:
        uid = await asyncio.to_thread(parse_creator_input, raw_input)
    except CatalogError as error:
        raise HTTPException(status_code=_catalog_error_status(error), detail=str(error))
    owner = _identity_owner(identity)
    existing = store.find_sub_by_uid(owner, uid)
    if existing:
        # 已订阅：不再起新同步（避免 conflict 噪音），返回既有订阅
        return {
            "sub": store.get_sub(existing["id"], identity),
            "sync": store.latest_sync(store.get_sub(existing["id"], identity)["creator_id"]),
            "created": False,
            "already_subscribed": True,
        }
    creator_id = store.upsert_creator("bilibili", uid)
    sub_id = store.upsert_sub(creator_id, owner)
    sync_id = sync.start_sync(creator_id, mode="incremental")
    return {
        "sub": store.get_sub(sub_id, identity),
        "sync": store.get_sync(sync_id),
        "created": True,
        "already_subscribed": False,
    }


@router.get("/bloggers")
async def list_bloggers(request: Request):
    identity = require_identity(request)
    bloggers = store.list_subs(_identity_owner(identity))
    counts = learned_mod.video_counts(
        _identity_owner(identity), [b["creator_id"] for b in bloggers]
    )
    for item in bloggers:
        state = counts.get(item["creator_id"], {})
        item["organized_count"] = state.get("organized_count", 0)
        item["subtitle_count"] = state.get("subtitle_count", 0)
        item["learned_count"] = item["organized_count"]
    return {"bloggers": bloggers}


@router.patch("/bloggers/{sub_id}")
async def update_blogger(sub_id: int, request: Request):
    identity = require_identity(request)
    _sub_or_404(sub_id, identity)
    body = await request.json()
    alias = (body or {}).get("alias")
    if alias is None or not isinstance(alias, str):
        raise HTTPException(status_code=400, detail="alias 必须是字符串")
    store.update_sub(sub_id, _identity_owner(identity), alias=alias.strip()[:64])
    return {"sub": store.get_sub(sub_id, identity)}


@router.delete("/bloggers/{sub_id}")
async def delete_blogger(sub_id: int, request: Request):
    identity = require_identity(request)
    _sub_or_404(sub_id, identity)
    try:
        result = store.remove_sub(sub_id, _identity_owner(identity))
    except Exception:
        logger.exception(f"退订失败 sub_id={sub_id}")
        raise HTTPException(status_code=500, detail="退订失败，请稍后重试")
    return result


@router.post("/bloggers/{sub_id}/sync")
async def sync_blogger(sub_id: int, request: Request):
    identity = require_identity(request)
    sub = _sub_or_404(sub_id, identity)
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    mode = (body or {}).get("mode") or "incremental"
    active = store.active_sync(sub["creator_id"])
    if active:
        return {"sync": active, "already_running": True}
    sync_id = sync.start_sync(sub["creator_id"], mode=mode)
    return {"sync": store.get_sync(sync_id), "already_running": False}


@router.get("/bloggers/{sub_id}/sync")
async def get_sync_status(sub_id: int, request: Request):
    identity = require_identity(request)
    sub = _sub_or_404(sub_id, identity)
    return {"sync": store.latest_sync(sub["creator_id"])}


@router.post("/bloggers/{sub_id}/sync/cancel")
async def cancel_sync(sub_id: int, request: Request):
    identity = require_identity(request)
    sub = _sub_or_404(sub_id, identity)
    return store.cancel_sync(sub["creator_id"])


@router.get("/bloggers/{sub_id}/deletion-preview")
async def preview_blogger_deletion(sub_id: int, request: Request):
    identity = require_identity(request)
    preview = store.preview_remove(sub_id, _identity_owner(identity))
    if not preview:
        raise HTTPException(status_code=404, detail="博主订阅不存在")
    return preview


@router.get("/bloggers/{sub_id}/videos")
async def list_blogger_videos(sub_id: int, request: Request):
    identity = require_identity(request)
    sub = _sub_or_404(sub_id, identity)
    params = request.query_params
    q = params.get("q", "")
    learned_filter = params.get("learned", "all")
    subtitle_only = params.get("has_subtitle", "") in ("1", "true")
    extra_where, extra_params = learned_mod.learned_exists_sql(_identity_owner(identity), learned_filter)
    if subtitle_only:
        subtitle_where, subtitle_params = learned_mod.subtitle_exists_sql(_identity_owner(identity))
        extra_where = f"({extra_where}) AND ({subtitle_where})" if extra_where else subtitle_where
        extra_params = [*extra_params, *subtitle_params]
    result = store.list_videos(
        sub["creator_id"],
        q=q,
        offset=int(params.get("offset") or 0),
        limit=int(params.get("limit") or 30),
        extra_where=extra_where,
        extra_params=extra_params,
        anchor_id=int(params["anchor_id"]) if params.get("anchor_id", "").isdigit() else None,
        locate_anchor=params.get("locate_anchor", "") in ("1", "true"),
    )
    # learned_total = 匹配 q 的已学总数（不受 learned 过滤影响）
    learned_scope_where, learned_scope_params = learned_mod.learned_exists_sql(
        _identity_owner(identity), "learned")
    learned_total = store.list_videos(
        sub["creator_id"], q=q, limit=1,
        extra_where=learned_scope_where, extra_params=learned_scope_params,
    )["total"]
    bvids = [item["bvid"] for item in result["items"]]
    content = learned_mod.content_by_bvid(identity, bvids)
    for item in result["items"]:
        states = content.get(item["bvid"], {})
        parts = {page for page, state in states.items() if state["module_count"]}
        item["url"] = _part_url(item["bvid"], 1)
        item["learned_parts"] = sorted(parts)
        item["is_learned"] = bool(parts)
        item["content"] = states.get(1, content_state())
        item["subtitle_parts"] = sorted(p for p, state in states.items() if state["has_subtitle"])
        item["organized_parts"] = sorted(parts)
        item["part_content"] = states
    subtitle_where, subtitle_params = learned_mod.subtitle_exists_sql(_identity_owner(identity))
    result["subtitle_total"] = store.list_videos(sub["creator_id"], q=q, limit=1,
        extra_where=subtitle_where, extra_params=subtitle_params)["total"]
    result["matched_total"] = store.list_videos(sub["creator_id"], q=q, limit=1)["total"]
    result["organized_total"] = learned_total
    result["learned_total"] = learned_total
    return result


@router.get("/bloggers/{sub_id}/videos/{video_id}/pages")
async def list_blogger_video_pages(sub_id: int, video_id: int, request: Request):
    identity = require_identity(request)
    sub = _sub_or_404(sub_id, identity)
    video = store.get_video(video_id)
    if not video or video["creator_id"] != sub["creator_id"]:
        raise HTTPException(status_code=404, detail="视频不存在")
    if not store.has_pages(video_id):
        client = BilibiliCatalogClient()
        try:
            view_data, pages = await asyncio.to_thread(client.parts, video["bvid"])
        except CatalogError as error:
            status = 409 if error.code == "rate_limit" else 502
            raise HTTPException(status_code=status, detail=str(error))
        store.replace_pages(video_id, [
            {
                "cid": page.get("cid"),
                "page": page.get("page") or index + 1,
                "part_title": page.get("part") or "",
                "duration": page.get("duration") or 0,
            }
            for index, page in enumerate(pages)
        ])
        # 顺带用详情修正目录项的简介/时长
        store.upsert_video(sub["creator_id"], {
            "bvid": video["bvid"],
            "title": video.get("title") or view_data.get("title") or "",
            "cover": video.get("cover") or view_data.get("pic") or "",
            "description": view_data.get("desc") or "",
            "published_at": video.get("published_at") or view_data.get("pubdate") or 0,
            "duration": video.get("duration") or 0,
        })
    content = learned_mod.content_by_bvid(identity, [video["bvid"]]).get(video["bvid"], {})
    rows = store.list_pages(video_id)
    for row in rows:
        row["url"] = _part_url(video["bvid"], row["page"])
        row["content"] = content.get(row["page"], content_state())
        row["is_learned"] = row["content"]["module_count"] > 0
    return {"pages": rows}


# ── 批量任务 ──


@router.post("/bloggers/{sub_id}/batches")
async def create_blogger_batch(sub_id: int, request: Request):
    identity = require_identity(request)
    sub = _sub_or_404(sub_id, identity)
    body = await request.json()
    mode = (body or {}).get("mode") or "full"
    selection = (body or {}).get("selection") or {}
    from core.auth import check_usage_limit
    allowed, used, limit = check_usage_limit(identity.get("user_id"), identity.get("guest_id"),
                                             identity.get("guest_sig"))
    try:
        batch = await asyncio.to_thread(
            batches_mod.create_batch,
            sub["creator_id"], selection, mode=mode, identity=_identity_owner(identity),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except CatalogError as error:
        raise HTTPException(status_code=502, detail=str(error))
    batch["usage"] = {"allowed": allowed, "used": used, "limit": limit}
    return batch


@router.get("/bloggers/{sub_id}/batches")
async def list_blogger_batches(sub_id: int, request: Request):
    identity = require_identity(request)
    sub = _sub_or_404(sub_id, identity)
    params = request.query_params
    return {"batches": batches_mod.list_batches(
        sub["creator_id"], _identity_owner(identity),
        limit=int(params.get("limit") or 20),
    )}


@router.get("/batches/{batch_id}")
async def get_blogger_batch(batch_id: str, request: Request):
    identity = require_identity(request)
    batch = batches_mod.get_batch(batch_id, _identity_owner(identity))
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    return batch


@router.post("/batches/{batch_id}/actions")
async def act_blogger_batch(batch_id: str, request: Request):
    identity = require_identity(request)
    body = await request.json()
    action = (body or {}).get("action") or ""
    try:
        return batches_mod.batch_action(batch_id, action, _identity_owner(identity))
    except ValueError as error:
        status = 404 if "不存在" in str(error) else 400
        raise HTTPException(status_code=status, detail=str(error))
