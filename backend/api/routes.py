from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
import urllib.request
import http.client
import uuid
import os
import re
import asyncio
from asyncio import Queue


def extract_url(text: str) -> str:
    """从用户输入中提取第一个 http/https URL，兼容手机分享的带标题文本。"""
    text = text.strip()
    m = re.search(r'https?://\S+', text)
    url = m.group(0).rstrip('.,;)】。') if m else text
    return _resolve_short_url(url)


def _resolve_short_url(url: str) -> str:
    """将短链解析为真实 URL（只取 Location，不跟随重定向）。"""
    # b23.tv → bilibili.com
    if re.match(r'https?://b23\.tv/', url):
        path = '/' + url.split('b23.tv/', 1)[1]
        try:
            conn = http.client.HTTPSConnection('b23.tv', timeout=10)
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
            pass
        return url

    # v.douyin.com → douyin.com/video/{id}
    if re.match(r'https?://v\.douyin\.com/', url):
        path = '/' + url.split('v.douyin.com/', 1)[1]
        try:
            conn = http.client.HTTPSConnection('v.douyin.com', timeout=10)
            conn.request('GET', path, headers={
                'User-Agent': 'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36',
            })
            resp = conn.getresponse()
            location = resp.getheader('Location') or ''
            vid = re.search(r'/video/(\d+)', location)
            if vid:
                return f'https://www.douyin.com/video/{vid.group(1)}'
        except Exception:
            pass
        return url

    return url

from core.downloader import VideoDownloader
from core.models import ParseRequest, DownloadRequest, VideoInfo, DownloadTask, ProgressData, SubtitleTrack

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
        info = downloader.parse_info(extract_url(req.url))
        return info
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析失败: {str(e)}")


@router.get("/api/thumbnail")
async def proxy_thumbnail(url: str):
    """代理缩略图请求，解决混合内容和防盗链问题。"""
    from urllib.parse import urlparse

    if url.startswith("http://"):
        url = "https://" + url[7:]

    # CDN 域名 → 所属平台 Referer 映射
    _CDN_REFERER = {
        'xhscdn.com':       'https://www.xiaohongshu.com/',
        'hdslb.com':        'https://www.bilibili.com/',
        'bilivideo.com':    'https://www.bilibili.com/',
        'douyinvod.com':    'https://www.douyin.com/',
        '365yg.com':        'https://www.douyin.com/',
        'amemv.com':        'https://www.douyin.com/',
        'pstatp.com':       'https://www.douyin.com/',
        'ixigua.com':       'https://www.ixigua.com/',
        'ytimg.com':        'https://www.youtube.com/',
        'googlevideo.com':  'https://www.youtube.com/',
    }

    netloc = urlparse(url).netloc
    referer = next(
        (v for k, v in _CDN_REFERER.items() if netloc.endswith(k)),
        None,
    )

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


def _download_subtitle_content(url: str, lang: str, is_auto: bool) -> tuple[str, str]:
    """用 yt-dlp 下载字幕文件，返回 (文件内容, 文件扩展名)。
    支持 YouTube 翻译字幕（lang 如 "zh-Hans-en" 表示从英文翻译的中文）。
    """
    import yt_dlp
    import tempfile
    import glob

    tmpdir = tempfile.mkdtemp(prefix='subtitle_')
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': True,
        'writesubtitles': True,
        'writeautomaticsub': True,  # 始终启用自动字幕（含翻译字幕）
        'subtitleslangs': [lang],
        'subtitlesformat': 'srt/vtt/json3/best',
        'outtmpl': os.path.join(tmpdir, '%(id)s'),
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.extract_info(url, download=True)

    # 查找下载的字幕文件
    candidates = glob.glob(os.path.join(tmpdir, '*'))
    sub_files = [f for f in candidates if os.path.isfile(f)
                 and os.path.splitext(f)[1].lower() in ('.srt', '.vtt', '.json3', '.srv1', '.srv2', '.srv3')]
    if not sub_files:
        # 尝试匹配所有文件
        sub_files = [f for f in candidates if os.path.isfile(f) and not f.endswith('.part')]
    if not sub_files:
        raise Exception('字幕下载失败，可能该视频没有此语言的字幕')

    sub_file = sub_files[0]
    ext = os.path.splitext(sub_file)[1].lstrip('.')
    with open(sub_file, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()

    # 清理临时目录
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    return content, ext


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
                pass  # 降级到外部翻译

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