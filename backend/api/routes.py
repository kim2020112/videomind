from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
import urllib.request
import http.client
import uuid
import os
import re
import asyncio
from asyncio import Queue

from core.pipeline.subtitle import _download_subtitle_content
from core.logging_config import get_logger

logger = get_logger(__name__)

from core.cache import save_video_info_cache


def extract_url(text: str) -> str:
    """从用户输入中提取第一个 http/https URL，兼容手机分享的带标题文本。"""
    if not text or not text.strip():
        raise ValueError("请输入有效的视频链接")
    text = text.strip()
    m = re.search(r'https?://\S+', text)
    if not m:
        raise ValueError("未检测到有效的视频链接，请输入包含 http/https 的 URL")
    url = m.group(0).rstrip('.,;)】。')
    return _resolve_short_url(url)


def _resolve_short_url(url: str) -> str:
    """将短链解析为真实 URL（只取 Location，不跟随重定向）。"""
    # b23.tv → bilibili.com
    if re.match(r'https?://b23\.tv/', url):
        path = '/' + url.split('b23.tv/', 1)[1]
        conn = http.client.HTTPSConnection('b23.tv', timeout=10)
        try:
            conn.request('GET', path, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            })
            resp = conn.getresponse()
            location = resp.getheader('Location')
            if location and 'bilibili.com' in location:
                bv = re.search(r'(BV\w+)', location)
                if bv:
                    return f'https://www.bilibili.com/video/{bv.group(1)}'
                return location
        except Exception:
            logger.warning(f"Bilibili短链接解析失败: {url[:80]}")
        finally:
            conn.close()
        return url

    # v.douyin.com → douyin.com/video/{id}
    if re.match(r'https?://v\.douyin\.com/', url):
        path = '/' + url.split('v.douyin.com/', 1)[1]
        conn = http.client.HTTPSConnection('v.douyin.com', timeout=10)
        try:
            conn.request('GET', path, headers={
                'User-Agent': 'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36',
            })
            resp = conn.getresponse()
            location = resp.getheader('Location') or ''
            vid = re.search(r'/video/(\d+)', location)
            if vid:
                return f'https://www.douyin.com/video/{vid.group(1)}'
        except Exception:
            logger.warning(f"抖音短链接解析失败: {url[:80]}")
        finally:
            conn.close()
        return url

    # bilibili.com（无 www）→ www.bilibili.com，避免 yt-dlp 403
    if re.match(r'https?://bilibili\.com/', url):
        url = url.replace('://bilibili.com/', '://www.bilibili.com/', 1)

    return url

from core.downloader import VideoDownloader
from core.models import ParseRequest, DownloadRequest, VideoInfo, DownloadTask, ProgressData, SubtitleTrack

router = APIRouter()

# CDN 域名 → 所属平台 Referer 映射（视频流代理 + 缩略图代理共用）
_CDN_REFERER = {
    'xhscdn.com':       'https://www.xiaohongshu.com/',
    'hdslb.com':        'https://www.bilibili.com/',
    'bilivideo.com':    'https://www.bilibili.com/',
    'bilibili.com':     'https://www.bilibili.com/',
    'douyinvod.com':    'https://www.douyin.com/',
    '365yg.com':        'https://www.douyin.com/',
    'amemv.com':        'https://www.douyin.com/',
    'pstatp.com':       'https://www.douyin.com/',
    'ixigua.com':       'https://www.ixigua.com/',
    'ytimg.com':        'https://www.youtube.com/',
    'googlevideo.com':  'https://www.youtube.com/',
    'youtube.com':      'https://www.youtube.com/',
}


def _get_cdn_referer(url: str) -> str | None:
    """根据 URL 域名匹配 CDN Referer。"""
    from urllib.parse import urlparse
    netloc = urlparse(url).netloc
    return next(
        (v for k, v in _CDN_REFERER.items() if netloc.endswith(k)),
        None,
    )


def _validate_public_url(url: str) -> None:
    """SSRF 防护：仅允许 http/https，且目标解析后不得为私网/环回/链路本地/保留地址。

    校验失败抛 HTTPException(400)。防止把代理端点当作打内网、云元数据（169.254.169.254）
    的跳板。DNS 解析后逐个 IP 校验，覆盖域名指向内网的情况。
    """
    import socket
    import ipaddress
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="仅支持 http/https 链接")
    host = parsed.hostname
    if not host:
        raise HTTPException(status_code=400, detail="无效的 URL")

    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="无法解析目标域名")

    for info in addr_infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise HTTPException(status_code=400, detail="拒绝访问内网地址")


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
        url = extract_url(req.url)
        info = downloader.parse_info(url)
        save_video_info_cache(url, info)
        return info
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析失败: {str(e)}")


@router.get("/api/video/refresh")
async def refresh_stream_url(url: str):
    """刷新过期的视频直链，轻量级（仅提取 formats，不完整 parse）。"""
    try:
        import time as _time
        import yt_dlp
        url = extract_url(url)
        ydl_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True, 'noplaylist': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        raw_formats = info.get('formats', [])
        combined = [
            f for f in raw_formats
            if (f.get('vcodec', 'none') or 'none') != 'none'
            and (f.get('acodec', 'none') or 'none') != 'none'
            and f.get('url')
        ]
        if combined:
            best = max(combined, key=lambda f: f.get('height') or 0)
        else:
            # DASH 降级：纯视频流
            video_only = [
                f for f in raw_formats
                if (f.get('vcodec', 'none') or 'none') != 'none'
                and (f.get('acodec', 'none') or 'none') == 'none'
                and f.get('url')
            ]
            if not video_only:
                return {"stream_url": None, "stream_expires_at": None}
            best = max(video_only, key=lambda f: f.get('height') or 0)
        return {
            "stream_url": best['url'],
            "stream_expires_at": int(_time.time()) + 1800,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"刷新失败: {str(e)}")


@router.get("/api/video/stream")
async def proxy_video_stream(url: str, request: Request, video_url: str = ""):
    """代理视频流请求，解决 Bilibili 等平台 CDN 的 Referer 限制。"""
    _validate_public_url(url)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    # 优先用原始视频 URL 推导 Referer（CDN 域名可能不在映射表中）
    referer = None
    if video_url:
        referer = _get_cdn_referer(video_url)
    if not referer:
        referer = _get_cdn_referer(url)
    if referer:
        headers["Referer"] = referer
    # 转发浏览器的 Range 请求（视频 seek 需要）
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=30)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"视频源请求失败: {str(e)}")

    def stream():
        try:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            resp.close()

    resp_headers = {
        "Content-Type": resp.headers.get("Content-Type", "video/mp4"),
        "Accept-Ranges": "bytes",
        "Access-Control-Allow-Origin": "*",
    }
    cl = resp.headers.get("Content-Length")
    if cl:
        resp_headers["Content-Length"] = cl
    cr = resp.headers.get("Content-Range")
    if cr:
        resp_headers["Content-Range"] = cr

    status_code = resp.status if resp.status in (200, 206) else 200
    return StreamingResponse(stream(), status_code=status_code, headers=resp_headers)


@router.get("/api/thumbnail")
async def proxy_thumbnail(url: str):
    """代理缩略图请求，解决混合内容和防盗链问题。"""
    if url.startswith("http://"):
        url = "https://" + url[7:]

    _validate_public_url(url)
    referer = _get_cdn_referer(url)

    def _fetch():
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read(), resp.headers.get("Content-Type", "image/jpeg")

    try:
        content, content_type = await asyncio.get_event_loop().run_in_executor(None, _fetch)
        return Response(content=content, media_type=content_type)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"缩略图获取失败: {e}")


def _parse_srt(content: str) -> list[dict]:
    """解析 SRT 字幕，返回 [{index, time, text}]。"""
    import re
    blocks = re.split(r'\n\s*\n', content.strip())
    entries = []
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        try:
            index = int(lines[0].strip())
        except ValueError:
            continue
        time_line = lines[1].strip()
        text = '\n'.join(lines[2:]).strip()
        if text:
            entries.append({'index': index, 'time': time_line, 'text': text})
    return entries


def _build_srt(entries: list[dict]) -> str:
    """从 [{index, time, text}] 重建 SRT 内容。"""
    parts = []
    for e in entries:
        parts.append(f"{e['index']}\n{e['time']}\n{e['text']}")
    return '\n\n'.join(parts) + '\n'


# 语言代码映射：前端代码 → MyMemory 代码
_LANG_MAP = {
    'zh-Hans': 'zh-CN', 'zh': 'zh-CN', 'zh-CN': 'zh-CN',
    'en': 'en-GB', 'en-US': 'en-US',
    'ja': 'ja-JP', 'ko': 'ko-KR',
    'fr': 'fr-FR', 'de': 'de-DE', 'es': 'es-ES',
    'pt': 'pt-PT', 'ru': 'ru-RU', 'it': 'it-IT',
}


def _map_lang(code: str) -> str:
    return _LANG_MAP.get(code, code)


def _translate_text(text: str, src: str, dest: str) -> str:
    """翻译单段文本。"""
    from deep_translator import MyMemoryTranslator
    try:
        return MyMemoryTranslator(source=_map_lang(src), target=_map_lang(dest)).translate(text)
    except Exception:
        return text  # 翻译失败返回原文


def _batch_translate(texts: list[str], src: str, dest: str, batch_size: int = 20) -> list[str]:
    """批量翻译文本列表。MyMemory 单次最多 500 字符，逐条翻译更可靠。"""
    from deep_translator import MyMemoryTranslator
    src_code = _map_lang(src)
    dest_code = _map_lang(dest)
    results = []
    for text in texts:
        try:
            translated = MyMemoryTranslator(source=src_code, target=dest_code).translate(text)
            results.append(translated if translated else text)
        except Exception:
            results.append(text)
    return results


@router.get("/api/subtitle")
async def download_subtitle(url: str, lang: str, auto: bool = False):
    """下载字幕文件。"""
    try:
        url = extract_url(url)
        content, ext = await asyncio.get_event_loop().run_in_executor(
            None, _download_subtitle_content, url, lang, auto
        )
        suffix = f".{lang}.auto.{ext}" if auto else f".{lang}.{ext}"
        return Response(
            content=content.encode('utf-8'),
            media_type='text/plain; charset=utf-8',
            headers={'Content-Disposition': f'attachment; filename="subtitle{suffix}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"字幕下载失败: {str(e)}")


@router.get("/api/subtitle/translate")
async def translate_subtitle(url: str, lang: str, target: str, auto: bool = False):
    """下载并翻译字幕文件。
    优先使用 YouTube 原生翻译（yt-dlp 的 automatic_captions 中已有翻译条目），
    失败时降级到外部翻译服务。
    """
    try:
        url = extract_url(url)

        # 优先尝试 YouTube 原生翻译：用 target-lang 格式直接下载翻译字幕
        # 例如 lang="en", target="zh-Hans" → 尝试下载 "zh-Hans-en"
        yt_translated = False
        if not auto and '-' not in lang:  # 避免对已翻译的条目重复处理
            yt_trans_code = f"{target}-{lang}"
            try:
                content, ext = await asyncio.get_event_loop().run_in_executor(
                    None, _download_subtitle_content, url, yt_trans_code, True
                )
                if content and len(content.strip()) > 10:
                    yt_translated = True
            except Exception:
                logger.warning(f"YouTube原生翻译失败，降级到外部翻译")

        if not yt_translated:
            content, ext = await asyncio.get_event_loop().run_in_executor(
                None, _download_subtitle_content, url, lang, auto
            )

        if yt_translated:
            # YouTube 原生翻译已获取，直接使用
            result = content
        elif ext == 'srt':
            entries = _parse_srt(content)
            if not entries:
                raise Exception('无法解析 SRT 字幕')
            texts = [e['text'] for e in entries]
            translated_texts = await asyncio.get_event_loop().run_in_executor(
                None, _batch_translate, texts, lang, target
            )
            for i, e in enumerate(entries):
                e['text'] = translated_texts[i] if i < len(translated_texts) else e['text']
            result = _build_srt(entries)
        else:
            # 对于 VTT 等其他格式，逐行翻译（保留格式）
            lines = content.split('\n')
            text_lines = []
            text_indices = []
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped and not stripped.startswith('WEBVTT') and not stripped.startswith('NOTE') \
                        and '-->' not in stripped and not stripped.isdigit():
                    text_lines.append(stripped)
                    text_indices.append(i)
            if text_lines:
                translated = await asyncio.get_event_loop().run_in_executor(
                    None, _batch_translate, text_lines, lang, target
                )
                for i, idx in enumerate(text_indices):
                    lines[idx] = translated[i] if i < len(translated) else lines[idx]
            result = '\n'.join(lines)

        suffix = f".{lang}.auto.{target}.{ext}" if auto else f".{lang}.{target}.{ext}"
        return Response(
            content=result.encode('utf-8'),
            media_type='text/plain; charset=utf-8',
            headers={'Content-Disposition': f'attachment; filename="subtitle{suffix}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"字幕翻译失败: {str(e)}")


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
        url = extract_url(data.get("url", ""))
        format_id = data.get("format_id", "best")
        concat_parts = data.get("concat_parts", False)
        selected_parts = data.get("selected_parts", None)

        task.status = "downloading"

        loop = asyncio.get_event_loop()

        async def run_download():
            try:
                file_path = await loop.run_in_executor(
                    None,
                    lambda: downloader.download(url, format_id, task_id,
                                                concat_parts=concat_parts,
                                                selected_parts=selected_parts)
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