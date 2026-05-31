from fastapi import APIRouter, Query, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from database import get_db
from core.cache import list_history_enhanced, toggle_favorite, get_learning_stats, get_all_tags, delete_cache
from core.vectorstore import query_chunks
from api.auth_routes import get_identity

router = APIRouter(prefix="/api", tags=["knowledge"])


@router.get("/videos")
async def list_videos(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    platform: Optional[str] = None,
):
    offset = (page - 1) * page_size
    with get_db() as conn:
        conditions = []
        params = []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if platform:
            conditions.append("platform = ?")
            params.append(platform)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM videos {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM videos {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [dict(r) for r in rows],
    }


@router.get("/videos/{video_id}")
async def get_video(video_id: int):
    with get_db() as conn:
        video = conn.execute(
            "SELECT * FROM videos WHERE id = ?", (video_id,)
        ).fetchone()
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")
        subtitles = conn.execute(
            "SELECT * FROM subtitles WHERE video_id = ?", (video_id,)
        ).fetchall()
        ai_outputs = conn.execute(
            "SELECT * FROM ai_outputs WHERE video_id = ?", (video_id,)
        ).fetchall()
    outputs_by_type = {}
    for o in ai_outputs:
        outputs_by_type[o["output_type"]] = o["content"]
    return {
        "video": dict(video),
        "subtitles": [dict(s) for s in subtitles],
        "ai_outputs": outputs_by_type,
    }


@router.delete("/videos/{video_id}")
async def delete_video(video_id: int):
    with get_db() as conn:
        video = conn.execute(
            "SELECT id FROM videos WHERE id = ?", (video_id,)
        ).fetchone()
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")
        conn.execute("DELETE FROM video_tags WHERE video_id = ?", (video_id,))
        conn.execute("DELETE FROM subtitles WHERE video_id = ?", (video_id,))
        conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))
        conn.execute("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM video_tags)")
    return {"ok": True}


@router.get("/tags")
async def list_tags():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM tags ORDER BY name").fetchall()
    return [dict(r) for r in rows]


# ──── 学习历史 ────

@router.get("/history")
async def list_history(
    request: Request,
    q: Optional[str] = None,
    tag: Optional[str] = None,
    platform: Optional[str] = None,
    sort: str = Query("newest", regex="^(newest|oldest)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """学习历史列表：支持搜索、标签过滤、平台过滤。按用户隔离。"""
    identity = get_identity(request)
    return list_history_enhanced(
        q=q, tag=tag, platform=platform, sort=sort, limit=limit, offset=offset,
        user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
        role=identity.get("role"),
    )


@router.post("/history/{url_hash}/favorite")
async def toggle_favorite_endpoint(url_hash: str, request: Request):
    """切换收藏状态。按用户隔离。"""
    identity = get_identity(request)
    new_state = toggle_favorite(url_hash, user_id=identity.get("user_id"), guest_id=identity.get("guest_id"))
    return {"is_favorite": new_state}


class BatchDeleteRequest(BaseModel):
    url_hashes: list[str]


@router.post("/history/batch-delete")
async def batch_delete_history(req: BatchDeleteRequest, request: Request):
    """批量删除学习历史记录。Admin 全局删除，普通用户按用户隔离。"""
    if not req.url_hashes:
        return {"ok": True, "deleted": 0}
    identity = get_identity(request)
    role = identity.get("role", "guest")
    deleted = 0
    for url_hash in req.url_hashes:
        if role == "admin":
            with get_db() as conn:
                row = conn.execute(
                    "SELECT url, fingerprint FROM ai_cache WHERE url_hash = ?",
                    (url_hash,),
                ).fetchone()
                conn.execute("DELETE FROM user_history WHERE url_hash = ?", (url_hash,))
            if row:
                delete_cache(row["url"], fingerprint=row["fingerprint"])
        else:
            with get_db() as conn:
                if identity.get("user_id"):
                    conn.execute(
                        "DELETE FROM user_history WHERE url_hash = ? AND user_id = ?",
                        (url_hash, identity["user_id"]),
                    )
                elif identity.get("guest_id"):
                    conn.execute(
                        "DELETE FROM user_history WHERE url_hash = ? AND guest_id = ?",
                        (url_hash, identity["guest_id"]),
                    )
        deleted += 1
    return {"ok": True, "deleted": deleted}


@router.delete("/history/{url_hash}")
async def delete_history(url_hash: str, request: Request):
    """删除学习历史记录。Admin 全局删除，普通用户按用户隔离。"""
    identity = get_identity(request)
    role = identity.get("role", "guest")
    if role == "admin":
        # Admin：全局删除 — 先查 ai_cache 拿 url/fingerprint，再逐个删除
        with get_db() as conn:
            row = conn.execute("SELECT url, fingerprint FROM ai_cache WHERE url_hash = ?", (url_hash,)).fetchone()
            conn.execute("DELETE FROM user_history WHERE url_hash = ?", (url_hash,))
        if row:
            delete_cache(row["url"], fingerprint=row["fingerprint"])
    else:
        with get_db() as conn:
            if identity.get("user_id"):
                conn.execute(
                    "DELETE FROM user_history WHERE url_hash = ? AND user_id = ?",
                    (url_hash, identity["user_id"]),
                )
            elif identity.get("guest_id"):
                conn.execute(
                    "DELETE FROM user_history WHERE url_hash = ? AND guest_id = ?",
                    (url_hash, identity["guest_id"]),
                )
    return {"ok": True}


@router.get("/history/stats")
async def get_stats(request: Request):
    """学习统计数据。按用户过滤。"""
    identity = get_identity(request)
    return get_learning_stats(user_id=identity.get("user_id"), guest_id=identity.get("guest_id"), role=identity.get("role"))


@router.get("/history/tags")
async def list_history_tags(request: Request):
    """获取标签（含使用次数）。按用户隔离。"""
    identity = get_identity(request)
    return get_all_tags(
        user_id=identity.get("user_id"), guest_id=identity.get("guest_id"),
        role=identity.get("role"),
    )


# ──── 全局知识搜索 ────

@router.get("/search")
async def knowledge_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
):
    """跨视频语义搜索，返回匹配片段 + 来源视频。"""
    results = await query_chunks(q, n_results=limit, video_id=None)
    items = []
    for i, doc in enumerate(results.get("documents", [])):
        meta = results.get("metadatas", [{}])[i] if i < len(results.get("metadatas", [])) else {}
        items.append({
            "video_title": meta.get("video_title", ""),
            "video_id": meta.get("video_id"),
            "snippet": doc[:300],
            "chunk_index": meta.get("chunk_index", 0),
        })
    return {"results": items, "query": q}
