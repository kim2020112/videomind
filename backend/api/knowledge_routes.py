from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from database import get_db
from core.cache import list_history_enhanced, toggle_favorite, get_learning_stats, get_all_tags, delete_cache
from core.vectorstore import query_chunks

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
        conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))
    return {"ok": True}


@router.get("/tags")
async def list_tags():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM tags ORDER BY name").fetchall()
    return [dict(r) for r in rows]


# ──── 学习历史 ────

@router.get("/history")
async def list_history(
    q: Optional[str] = None,
    tag: Optional[str] = None,
    platform: Optional[str] = None,
    sort: str = Query("newest", regex="^(newest|oldest)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """学习历史列表：支持搜索、标签过滤、平台过滤。"""
    return list_history_enhanced(q=q, tag=tag, platform=platform, sort=sort, limit=limit, offset=offset)


@router.post("/history/{url_hash}/favorite")
async def toggle_favorite_endpoint(url_hash: str):
    """切换收藏状态。"""
    new_state = toggle_favorite(url_hash)
    return {"is_favorite": new_state}


@router.delete("/history/{url_hash}")
async def delete_history(url_hash: str):
    """删除学习历史记录。"""
    with get_db() as conn:
        row = conn.execute("SELECT url FROM ai_cache WHERE url_hash = ?", (url_hash,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="记录不存在")
        delete_cache(row[0])
    return {"ok": True}


@router.get("/history/stats")
async def get_stats():
    """学习统计数据。"""
    return get_learning_stats()


@router.get("/history/tags")
async def list_history_tags():
    """获取所有标签（含使用次数）。"""
    return get_all_tags()


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
