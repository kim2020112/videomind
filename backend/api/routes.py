from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
import urllib.request
import uuid
import os
from asyncio import Queue

from core.downloader import VideoDownloader
from core.models import ParseRequest, DownloadRequest, VideoInfo, DownloadTask, ProgressData

router = APIRouter()

# 全局下载器实例
downloader = VideoDownloader(output_dir=os.path.join(os.path.dirname(os.path.dirname(__file__)), "downloads"))

# 任务存储（内存）
tasks: dict[str, DownloadTask] = {}


@router.get("/api/health")
async def health():
    return {"status": "ok"}


@router.post("/api/parse", response_model=VideoInfo)
async def parse_video(req: ParseRequest):
    """解析视频链接，返回视频信息和可用格式列表。"""
    try:
        info = downloader.parse_info(req.url)
        return info
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析失败: {str(e)}")


@router.get("/api/thumbnail")
async def proxy_thumbnail(url: str):
    """代理缩略图请求，绕过防盗链。自动升级 http 为 https。"""
    import asyncio

    # B站等平台的缩略图需要 https，自动升级
    if url.startswith("http://"):
        url = "https://" + url[7:]

    def _fetch():
        req = urllib.request.Request(url, headers={
            "Referer": "https://www.bilibili.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read(), resp.headers.get("Content-Type", "image/jpeg")

    try:
        content, content_type = await asyncio.get_event_loop().run_in_executor(None, _fetch)
        return Response(content=content, media_type=content_type)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"缩略图获取失败: {e}")


@router.post("/api/download")
async def start_download(req: DownloadRequest):
    """创建下载任务，返回 WebSocket 连接地址。"""
    task_id = uuid.uuid4().hex[:12]

    task = DownloadTask(
        task_id=task_id,
        title="准备下载...",
        status="pending",
    )
    tasks[task_id] = task

    return {
        "task_id": task_id,
        "ws_url": f"/ws/download/{task_id}",
    }


@router.websocket("/ws/download/{task_id}")
async def download_progress(websocket: WebSocket, task_id: str):
    """WebSocket 推送下载进度。"""
    await websocket.accept()

    if task_id not in tasks:
        await websocket.send_json({"status": "error", "error": "任务不存在"})
        await websocket.close()
        return

    task = tasks[task_id]
    progress_queue: Queue = Queue()
    downloader.register_progress_queue(task_id, progress_queue)

    try:
        # 接收下载指令
        data = await websocket.receive_json()
        url = data.get("url", "")
        format_id = data.get("format_id", "best")

        task.status = "downloading"

        import asyncio
        loop = asyncio.get_event_loop()

        async def run_download():
            try:
                file_path = await loop.run_in_executor(
                    None,
                    lambda: downloader.download(url, format_id, task_id)
                )
                task.status = "completed"
                task.file_path = file_path
                task.progress = 100
                # 完成消息由 downloader 内部通过 queue 推送，这里不重复发
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                progress_queue.put_nowait(ProgressData(
                    status="failed",
                    percent=0,
                    error=str(e),
                ))

        asyncio.create_task(run_download())

        # 持续推送进度直到完成或失败
        while True:
            try:
                progress: ProgressData = await asyncio.wait_for(
                    progress_queue.get(), timeout=300
                )
                task.progress = progress.percent
                if progress.speed:
                    task.speed = progress.speed
                if progress.eta:
                    task.eta = progress.eta
                if progress.file_path:
                    task.file_path = progress.file_path

                await websocket.send_json(progress.model_dump())

                if progress.status in ("completed", "failed"):
                    break

            except asyncio.TimeoutError:
                await websocket.send_json({"status": "failed", "percent": 0, "error": "下载超时"})
                break
            except WebSocketDisconnect:
                break
            except Exception:
                break

    except WebSocketDisconnect:
        pass
    finally:
        downloader.unregister_progress_queue(task_id)


@router.get("/api/files/{task_id}")
async def get_downloaded_file(task_id: str):
    """获取已下载的视频文件。"""
    task = tasks.get(task_id)
    if not task or not task.file_path:
        raise HTTPException(status_code=404, detail="文件不存在或任务未完成")

    file_path = task.file_path
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件已被删除")

    file_name = os.path.basename(file_path)
    return FileResponse(
        path=file_path,
        filename=file_name,
        media_type="application/octet-stream",
    )


@router.get("/api/downloads")
async def list_downloads():
    completed = [
        {"task_id": t.task_id, "title": t.title, "status": t.status, "file_path": t.file_path}
        for t in tasks.values()
        if t.status in ("completed", "failed")
    ]
    return {"downloads": completed}