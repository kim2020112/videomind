"""Read-only workspace snapshots and resumable, owner-scoped learning tasks."""
import asyncio
import json
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from api.routes import extract_url
from api.security import require_identity, ensure_public_http_url
from core import job_store, job_signals, learning
from core.auth import add_user_history
from core.cache import _url_hash, get_video_info_cache
from core.features import is_ai_available
from core.video import canonical_video_url
from core.summary_models import SummarizeRequest, QaGenerationRequest
from database import get_db

router = APIRouter(prefix="/api", tags=["learning"])


class PrepareRequest(BaseModel):
    url: str
    lang: str = ""
    request_key: str = Field(default_factory=lambda: uuid.uuid4().hex, max_length=100)
    refresh_subtitle: bool = False


class GenerateRequest(PrepareRequest):
    targets: list[Literal["summary", "mindmap", "notes", "qa"]] = Field(min_length=1, max_length=4)
    force: bool = False
    input_source: Literal["subtitle", "description"] = "subtitle"


class VisitRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4096)


def owner(identity):
    return {"user_id": identity.get("user_id"), "guest_id": identity.get("guest_id")}


def normalize(url):
    url = extract_url(url)
    ensure_public_http_url(url)
    info = get_video_info_cache(url)
    return canonical_video_url(url, info) if info else url


def submit(req, identity, targets):
    url = normalize(req.url)
    snapshot = learning.workspace(url, identity)
    source = getattr(req, "input_source", "subtitle")
    needs_generation = bool(targets) and (getattr(req, "force", False) or
        (not snapshot["artifacts"].get("description_summary") if source == "description" else
         any(snapshot["modules"][t]["status"] != "done" or snapshot["modules"][t]["stale"] for t in targets)))
    if needs_generation and not is_ai_available():
        raise HTTPException(503, "AI 功能暂不可用；仍可获取和转录字幕")
    if getattr(req, "input_source", "subtitle") == "description" and targets != ["summary"]:
        raise HTTPException(422, "基于简介仅支持生成摘要")
    payload = req.model_dump(exclude={"url", "lang"})
    payload["targets"] = list(dict.fromkeys(targets))
    active = job_store.find_active_job(_url_hash(url), **owner(identity))
    if active and active.get("payload", {}).get("request_key") != req.request_key:
        if active["job_type"] != "learning" or any(
            active.get("payload", {}).get(key) != payload.get(key)
            for key in ("targets", "force", "refresh_subtitle", "input_source")
        ):
            raise HTTPException(409, "当前视频已有任务，请完成或取消后再提交新的选择")
        return active
    admission_token = uuid.uuid4().hex
    task_id = job_store.create_job(_url_hash(url), url, **owner(identity), lang=req.lang,
                                   payload={**payload, "_admission_pending": True,
                                            "_admission_token": admission_token}, job_type="learning")
    job = job_store.get_job(task_id, **owner(identity))
    if job["url"] != url or job.get("lang", "") != req.lang or any(job["payload"].get(k) != payload.get(k) for k in ("targets", "force", "input_source", "refresh_subtitle")):
        raise HTTPException(409, "请求标识已用于其他生成操作")
    # An idempotent concurrent request must not admit another submitter's job
    # before that submitter finishes quota/history initialization.
    if job["payload"].get("_admission_token") != admission_token:
        return job
    try:
        if job["status"] == "queued" and targets and needs_generation:
            try:
                learning.reserve_usage(job)
            except ValueError as exc:
                raise HTTPException(429, str(exc)) from exc
        info = get_video_info_cache(url) or {}
        add_user_history(**owner(identity), url_hash=_url_hash(url), url=url,
                         title=info.get("title", ""), platform=info.get("extractor", ""), status=job["status"])
        learning.restore_subtitle(url, identity)
        job_store.update_job(task_id, payload=payload)
    except Exception as exc:
        learning.release_usage(task_id)
        current = job_store.get_job(task_id)
        if current and current["status"] == "queued":
            message = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
            job_store.update_job(task_id, status="failed", error=message, message=message, payload=payload)
        raise
    return job_store.get_job(task_id, **owner(identity))


@router.get("/workspace")
async def get_workspace(request: Request, url: str = Query(...)):
    identity = require_identity(request)
    return await run_in_threadpool(lambda: learning.workspace(normalize(url), identity))


@router.post("/workspace/visit")
async def visit_workspace(req: VisitRequest, request: Request):
    identity = require_identity(request)
    return await run_in_threadpool(lambda: learning.record_visit(normalize(req.url), identity))


@router.delete("/workspace/subtitle")
async def clear_workspace_subtitle(req: VisitRequest, request: Request):
    identity = require_identity(request)
    def clear():
        try:
            return learning.clear_subtitle(normalize(req.url), identity)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
    return await run_in_threadpool(clear)


@router.post("/subtitle/prepare")
async def prepare_subtitle(req: PrepareRequest, request: Request):
    return JSONResponse(status_code=202, content=await run_in_threadpool(submit, req, require_identity(request), []))


@router.post("/learning/generate")
async def generate_learning(req: GenerateRequest, request: Request):
    return JSONResponse(status_code=202, content=await run_in_threadpool(submit, req, require_identity(request), req.targets))


@router.post("/tasks/{task_id}/resume")
async def resume_task(task_id: str, request: Request):
    identity = require_identity(request)
    job = job_store.get_job(task_id, **owner(identity))
    if not job:
        raise HTTPException(404, "任务不存在")
    if job["status"] != "awaiting_confirmation":
        raise HTTPException(409, "该任务当前不需要确认")
    if job["payload"].get("targets"):
        try:
            learning.reserve_usage(job)
        except ValueError as exc:
            raise HTTPException(429, str(exc)) from exc
    with get_db() as conn:
        updated = conn.execute(
            "UPDATE background_jobs SET payload_json = ?, status = 'queued', message = '已确认转录，等待后台处理' "
            "WHERE id = ? AND status = 'awaiting_confirmation' AND cancel_requested = 0",
            (json.dumps({**job["payload"], "allow_transcription": True}, ensure_ascii=False), task_id),
        ).rowcount
    if not updated:
        learning.release_usage(task_id)
        raise HTTPException(409, "任务状态已变化")
    job_signals.notify(task_id)
    return job_store.get_job(task_id, **owner(identity))


async def event_stream(task_id, identity, after=0, disconnected=None):
    previous_state = None
    async with job_signals.subscribe(task_id) as signal:
        while True:
            signal.clear()
            if disconnected and await disconnected():
                return
            job = job_store.get_job(task_id, **owner(identity))
            if not job:
                return
            rows = learning.events_after(task_id, after)
            for row in rows:
                after = row["id"]
                yield f"id: {after}\ndata: {row['event_json']}\n\n".encode()
            if len(rows) == 200:
                continue
            # Read status before the events: a terminal transition occurring
            # during the read must not close the stream ahead of its last event.
            if job["status"] in job_store.TERMINAL_STATUSES or job["status"] == "awaiting_confirmation":
                yield ("data: " + json.dumps({"type": "task_state", "data": job}, ensure_ascii=False) + "\n\n").encode()
                return
            state = (job["status"], job["progress"], job["message"], job["queue_position"], job["cancel_requested"])
            if state != previous_state:
                previous_state = state
                yield ("data: " + json.dumps({"type": "task_progress", "data": job}, ensure_ascii=False) + "\n\n").encode()
            yield b": heartbeat\n\n"
            await signal.wait(timeout=1.0)


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: str, request: Request, after: int = Query(0, ge=0)):
    identity = require_identity(request)
    if not job_store.get_job(task_id, **owner(identity)):
        raise HTTPException(404, "任务不存在")
    try:
        after = max(after, int(request.headers.get("last-event-id", "0")))
    except ValueError:
        raise HTTPException(422, "无效的事件编号")
    return StreamingResponse(event_stream(task_id, identity, after, request.is_disconnected), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# Compatibility endpoints use the same durable tasks, including transcription consent.
@router.get("/subtitle/text")
async def subtitle_text(request: Request, url: str, lang: str = ""):
    identity = require_identity(request)
    url = normalize(url)
    snapshot = learning.workspace(url, identity)
    sub = snapshot["subtitle"]
    if snapshot["subtitle_cleared"]:
        return {"text": "", "subtitle_cleared": True, "lang": lang, "name": ""}
    if sub:
        return {**sub, "lang": sub["language"], "name": sub["source"]}
    task = submit(PrepareRequest(url=url, lang=lang), identity, [])
    return JSONResponse(status_code=202, content={"background": True, **task})


@router.post("/summarize/stream")
async def summarize_compat(req: SummarizeRequest, request: Request):
    identity = require_identity(request)
    if req.mode == "subtitle":
        task = submit(PrepareRequest(url=req.url, lang=req.lang or "", refresh_subtitle=True), identity, [])
    else:
        targets = list(learning.TARGETS) if req.mode == "full" else [req.mode]
        if any(t not in learning.TARGETS for t in targets):
            raise HTTPException(422, "未知生成模块")
        task = submit(GenerateRequest(url=req.url, lang=req.lang or "", force=req.force, targets=targets), identity, targets)

    async def stream():
        yield ("data: " + json.dumps({"type": "background_started", "data": task}, ensure_ascii=False) + "\n\n").encode()
        async for data in event_stream(task["task_id"], identity, disconnected=request.is_disconnected):
            if data.startswith(b"id:"):
                event = json.loads(data.decode().split("data: ", 1)[1])
                if event["type"] == "module_event":
                    inner = event["data"]
                    yield ("data: " + json.dumps({"type": inner["type"], "data": inner["data"]}, ensure_ascii=False) + "\n\n").encode()
                elif event["type"] == "artifact_saved":
                    item = event["data"]
                    kind, content = {"summary": ("result", item["content"]), "mindmap": ("mindmap", {"markdown": item["content"]}),
                                     "notes": ("notes", {"markdown": item["content"]}), "qa": ("qa_pairs", item["content"])}[item["target"]]
                    yield ("data: " + json.dumps({"type": kind, "data": content}, ensure_ascii=False) + "\n\n").encode()
                else:
                    yield data
            else:
                yield data
        # Cache-only tasks also need to replay their existing artifacts to old clients.
        saved = learning.workspace(task["url"], identity)
        for target in task["payload"].get("targets", []):
            content = saved["artifacts"].get(learning.KEYS[target])
            if content:
                kind, value = {"summary": ("result", content), "mindmap": ("mindmap", {"markdown": content}),
                               "notes": ("notes", {"markdown": content}), "qa": ("qa_pairs", content)}[target]
                yield ("data: " + json.dumps({"type": kind, "data": value}, ensure_ascii=False) + "\n\n").encode()
        yield b'data: {"type":"done","data":{}}\n\n'
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/summarize")
async def summarize_sync_compat(req: SummarizeRequest, request: Request):
    targets = list(learning.TARGETS) if req.mode == "full" else [req.mode]
    if req.mode == "subtitle":
        return await prepare_subtitle(PrepareRequest(url=req.url, lang=req.lang or "", refresh_subtitle=True), request)
    return await generate_learning(GenerateRequest(url=req.url, lang=req.lang or "", targets=targets, force=req.force), request)


@router.post("/qa/stream")
async def qa_compat(req: QaGenerationRequest, request: Request):
    if req.url:
        return await summarize_compat(SummarizeRequest(url=req.url, force=req.force, mode="qa"), request)
    from api.stream_routes import qa_stream
    return await qa_stream(req, request)
