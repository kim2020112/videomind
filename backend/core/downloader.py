import yt_dlp
import uuid
import os
import math
from typing import Optional, Callable
from asyncio import Queue

from .models import VideoInfo, FormatOption, ProgressData


def _format_filesize(size_bytes: Optional[int]) -> Optional[str]:
    if not size_bytes:
        return None
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


class VideoDownloader:
    """yt-dlp 核心封装，提供视频解析和下载能力。"""

    def __init__(self, output_dir: str = "downloads", ffmpeg_location: Optional[str] = None):
        self.output_dir = output_dir
        self.ffmpeg_location = ffmpeg_location
        self._progress_queues: dict[str, Queue] = {}
        os.makedirs(output_dir, exist_ok=True)

    def register_progress_queue(self, task_id: str, queue: Queue):
        self._progress_queues[task_id] = queue

    def unregister_progress_queue(self, task_id: str):
        self._progress_queues.pop(task_id, None)

    def _make_progress_hook(self, task_id: str):
        def progress_hook(d):
            queue = self._progress_queues.get(task_id)
            if queue is None:
                return
            try:
                if d['status'] == 'downloading':
                    total = d.get('total_bytes') or d.get('total_bytes_estimate')
                    downloaded = d.get('downloaded_bytes', 0)
                    percent = (downloaded / total * 100) if total else 0
                    speed_val = d.get('speed')
                    speed_str = _format_filesize(speed_val) + '/s' if speed_val else None
                    data = ProgressData(
                        status='downloading',
                        percent=round(percent, 1),
                        speed=speed_str,
                        eta=d.get('eta'),
                        downloaded=downloaded,
                        total=total,
                    )
                    queue.put_nowait(data)
                elif d['status'] == 'finished':
                    data = ProgressData(
                        status='processing',
                        percent=100,
                        file_path=d.get('filename'),
                    )
                    queue.put_nowait(data)
            except Exception:
                pass  # 进度推送失败不应中断下载
        return progress_hook

    def parse_info(self, url: str) -> VideoInfo:
        """解析视频链接，返回视频信息（不下载）。"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        raw_formats = info.get('formats', [])
        formats = []

        # 1. 始终提供"最佳画质"选项：yt-dlp 自动选最高质量并合并音视频
        formats.append(FormatOption(
            format_id='bestvideo+bestaudio/best',
            ext='mp4',
            resolution='best',
            is_combined=True,
            is_best=True,
            label='最佳画质（自动合并音视频）',
            format_note='推荐',
        ))

        # 2. 按分辨率分组，每个分辨率保留最佳编码（优先 avc1 兼容性好）
        #    对于视频流，下载时附加 +bestaudio 自动合并音频
        codec_priority = {'avc1': 0, 'h264': 0, 'hev1': 1, 'hevc': 1, 'av01': 2, 'vp9': 3}
        height_to_fmt: dict[int, dict] = {}
        for f in raw_formats:
            vcodec = f.get('vcodec', 'none') or 'none'
            acodec = f.get('acodec', 'none') or 'none'
            height = f.get('height')
            if not height or vcodec == 'none':
                continue
            # 取编码优先级（越小越优先）
            codec_key = vcodec.split('.')[0].lower()
            priority = codec_priority.get(codec_key, 99)
            existing = height_to_fmt.get(height)
            if existing is None or priority < existing['priority']:
                height_to_fmt[height] = {'f': f, 'priority': priority}

        for height in sorted(height_to_fmt.keys(), reverse=True):
            f = height_to_fmt[height]['f']
            vcodec = f.get('vcodec', 'none') or 'none'
            acodec = f.get('acodec', 'none') or 'none'
            is_video_only = vcodec != 'none' and acodec == 'none'
            is_combined = vcodec != 'none' and acodec != 'none'
            raw_id = f.get('format_id', '')
            filesize = f.get('filesize') or f.get('filesize_approx')
            size_str = _format_filesize(filesize)

            if is_video_only:
                # 视频流：下载时自动附加最佳音频
                download_id = f"{raw_id}+bestaudio/{raw_id}"
                label = f"{height}p MP4（视频+音频）"
                if size_str:
                    label += f"，约 {size_str}"
            else:
                download_id = raw_id
                label = f"{height}p MP4（合并流）"
                if size_str:
                    label += f"，{size_str}"

            formats.append(FormatOption(
                format_id=download_id,
                ext=f.get('ext', 'mp4'),
                resolution=f.get('resolution'),
                height=height,
                width=f.get('width'),
                fps=f.get('fps'),
                vcodec=vcodec,
                acodec=acodec,
                filesize=filesize,
                filesize_str=size_str,
                tbr=f.get('tbr'),
                format_note=f.get('format_note'),
                is_audio_only=False,
                is_video_only=is_video_only,
                is_combined=is_combined,
                label=label,
            ))

        # 3. 音频流：取最高码率的几个
        audio_fmts = [
            f for f in raw_formats
            if (f.get('acodec', 'none') or 'none') != 'none'
            and (f.get('vcodec', 'none') or 'none') == 'none'
        ]
        audio_fmts.sort(key=lambda f: f.get('tbr') or 0, reverse=True)
        seen_audio_ext: set[str] = set()
        for f in audio_fmts[:4]:
            ext = f.get('ext', 'm4a')
            if ext in seen_audio_ext:
                continue
            seen_audio_ext.add(ext)
            filesize = f.get('filesize') or f.get('filesize_approx')
            size_str = _format_filesize(filesize)
            tbr = f.get('tbr')
            label = f"仅音频 {ext.upper()}"
            if tbr:
                label += f"（{int(tbr)}kbps）"
            if size_str:
                label += f"，{size_str}"
            formats.append(FormatOption(
                format_id=f.get('format_id', ''),
                ext=ext,
                acodec=f.get('acodec'),
                filesize=filesize,
                filesize_str=size_str,
                tbr=tbr,
                is_audio_only=True,
                label=label,
            ))

        return VideoInfo(
            title=info.get('title', ''),
            webpage_url=info.get('webpage_url', url),
            duration=info.get('duration'),
            duration_string=info.get('duration_string'),
            thumbnail=info.get('thumbnail'),
            description=(info.get('description', '') or '')[:500],
            uploader=info.get('uploader'),
            view_count=info.get('view_count'),
            upload_date=info.get('upload_date'),
            extractor=info.get('extractor'),
            formats=formats,
        )

    def download(self, url: str, format_id: str, task_id: Optional[str] = None) -> str:
        """下载视频，返回下载完成的文件路径。"""
        if task_id is None:
            task_id = uuid.uuid4().hex[:12]

        output_template = os.path.join(self.output_dir, '%(title).100s.%(ext)s')

        ydl_opts = {
            'format': format_id,
            'outtmpl': output_template,
            'progress_hooks': [self._make_progress_hook(task_id)],
            'merge_output_format': 'mp4',
            'quiet': True,
            'no_warnings': True,
            'continuedl': True,
            'retries': 3,
            'fragment_retries': 3,
            'concurrent_fragment_downloads': 4,
        }

        if self.ffmpeg_location:
            ydl_opts['ffmpeg_location'] = self.ffmpeg_location

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)

            # yt-dlp 可能修改扩展名（合并后），找实际存在的文件
            if not os.path.exists(file_path):
                base = os.path.splitext(file_path)[0]
                for ext in ['.mp4', '.mkv', '.webm', '.flv', '.avi']:
                    candidate = base + ext
                    if os.path.exists(candidate):
                        file_path = candidate
                        break

            # 推送完成状态
            queue = self._progress_queues.get(task_id)
            if queue:
                queue.put_nowait(ProgressData(
                    status='completed',
                    percent=100,
                    file_path=file_path,
                ))

            return file_path