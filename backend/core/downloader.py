import yt_dlp
import uuid
import os
import math
import shutil
import tempfile
import time
from typing import Optional, Callable
from asyncio import Queue

from .models import VideoInfo, FormatOption, ProgressData, VideoPart, VideoChapter, SubtitleTrack
from .video import selected_video_part_index, video_duration_for_url
from .bilibili import ydl_opts_for, ytdlp_error_message, youtube_dl
from .bilibili_guard import BilibiliAccessBlocked, guarded_get

# 下载清理策略
_MAX_DOWNLOADS = 20       # 最多保留 20 个下载
_MAX_AGE_DAYS = 7         # 超过 7 天自动删除


def _cleanup_downloads(output_dir: str):
    """清理过期和超额的下载目录。"""
    if not os.path.isdir(output_dir):
        return
    entries = []
    for name in os.listdir(output_dir):
        path = os.path.join(output_dir, name)
        if os.path.isdir(path):
            entries.append((path, os.path.getmtime(path)))
    # 按修改时间排序（最新在前）
    entries.sort(key=lambda x: x[1], reverse=True)
    now = time.time()
    cutoff = now - _MAX_AGE_DAYS * 86400
    for i, (path, mtime) in enumerate(entries):
        if mtime < cutoff or i >= _MAX_DOWNLOADS:
            shutil.rmtree(path, ignore_errors=True)


def _is_bilibili(url: str) -> bool:
    return 'bilibili.com' in url or 'b23.tv' in url


def _fetch_bilibili_parts(url: str) -> list[VideoPart]:
    import re
    import json
    import urllib.request
    m = re.search(r'(BV\w+)', url)
    if not m:
        return []
    bvid = m.group(1)
    try:
        response = guarded_get(
            f'https://api.bilibili.com/x/player/pagelist?bvid={bvid}',
            headers={'Referer': 'https://www.bilibili.com/'}, timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        if data.get('code') != 0 or not data.get('data'):
            return []
        pages = data['data']
        if len(pages) <= 1:
            return []
        return [VideoPart(index=p['page'], title=p['part'], cid=p.get('cid'), duration=p.get('duration')) for p in pages]
    except BilibiliAccessBlocked:
        raise
    except Exception:
        return []


def _retryable_parse_error(error: Exception) -> bool:
    """Retry transient transport errors, never login/risk/content failures."""
    from yt_dlp.networking.exceptions import TransportError
    pending = [error]
    seen = set()
    transient = False
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        status = getattr(item, 'status', None) or getattr(item, 'status_code', None) or getattr(item, 'code', None)
        if isinstance(status, int):
            if 400 <= status < 500:
                return False
            transient = transient or 500 <= status < 600
        transient = transient or isinstance(item, (TransportError, TimeoutError, ConnectionError))
        for name in ('cause', '__cause__', '__context__'):
            nested = getattr(item, name, None)
            if isinstance(nested, BaseException):
                pending.append(nested)
        info = getattr(item, 'exc_info', None)
        if isinstance(info, tuple) and len(info) > 1 and isinstance(info[1], BaseException):
            pending.append(info[1])
    return transient


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
        _cleanup_downloads(output_dir)

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
            'noplaylist': True,
            'listsubtitles': True,
            'extractor_retries': 0,
            'retries': 0,
        }
        ydl_opts.update(ydl_opts_for(url))
        last_err = None
        for attempt in range(1 if _is_bilibili(url) else 3):
            try:
                with youtube_dl(ydl_opts, url) as ydl:
                    info = ydl.extract_info(url, download=False)
                break
            except BilibiliAccessBlocked:
                raise
            except Exception as e:
                last_err = e
                if _is_bilibili(url) or attempt >= 2 or not _retryable_parse_error(e):
                    raise RuntimeError(ytdlp_error_message(e)) from e
                time.sleep(2 * (2 ** attempt))
        else:
            raise RuntimeError(ytdlp_error_message(last_err)) from last_err

        raw_formats = info.get('formats', [])
        formats = []

        # 1. 按分辨率分组，每个分辨率保留最佳编码（优先 avc1 兼容性好）
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

        # 2. 标记最高分辨率格式为"推荐"
        for fmt in formats:
            if not fmt.is_audio_only:
                fmt.is_best = True
                fmt.format_note = '推荐'
                break

        # 3. 音频流：取最高码率的几个
        audio_fmts = [
            f for f in raw_formats
            if (f.get('acodec', 'none') or 'none') != 'none'
            and (f.get('vcodec', 'none') or 'none') == 'none'
        ]
        audio_fmts.sort(key=lambda f: f.get('tbr') or 0, reverse=True)
        audio_stream_url = audio_fmts[0].get('url') if audio_fmts else None
        audio_stream_expires_at = int(time.time()) + 1800 if audio_stream_url else None
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

        parts = _fetch_bilibili_parts(url) if _is_bilibili(url) else []

        # 清理标题：yt-dlp 对多P视频会在标题后追加 " pNN 分P名称"，需要去掉
        title = info.get('title', '')
        if parts:
            import re as _re
            title = _re.sub(r'\s+p\d{2,}\s+.*$', '', title).strip()

        # 基础 URL 展示全集总时长；显式分 P 必须保留所选分 P 时长，供 Whisper 使用。
        video_duration = info.get('duration')
        if parts and len(parts) > 1:
            duration_info = {**info, 'parts': parts}
            if selected_video_part_index(url, duration_info) is not None:
                video_duration = video_duration_for_url(url, duration_info)
            else:
                total_parts_duration = sum(p.duration for p in parts if p.duration)
                if total_parts_duration > 0:
                    video_duration = total_parts_duration

        # ── 基于码率的统一文件大小估算 ──
        # 用码率(kbps) × 当前请求范围时长(秒)统一估算，前端再按所选分 P 比例换算。

        # 找出最佳音频流的码率（视频流估算文件大小时需加上）
        best_audio_tbr = 0
        for f in raw_formats:
            vcodec = f.get('vcodec', 'none') or 'none'
            acodec = f.get('acodec', 'none') or 'none'
            tbr = f.get('tbr') or 0
            if acodec != 'none' and vcodec == 'none':
                best_audio_tbr = max(best_audio_tbr, tbr)

        # 找一个有 filesize 的格式作为参考基准（给无码率的格式用）
        ref_bytes_per_kbps = None
        for fmt in formats:
            if fmt.filesize and fmt.tbr and fmt.tbr > 0:
                ref_bytes_per_kbps = fmt.filesize / fmt.tbr
                break

        for fmt in formats:
            effective_tbr = fmt.tbr or 0
            # 视频流格式下载时会自动合并 +bestaudio，估算时需加上音频码率
            if fmt.is_video_only and best_audio_tbr > 0 and effective_tbr > 0:
                effective_tbr += best_audio_tbr
            if effective_tbr > 0 and video_duration:
                fmt.filesize = int(effective_tbr * 1000 / 8 * video_duration)
            elif ref_bytes_per_kbps and fmt.tbr and fmt.tbr > 0 and video_duration:
                fmt.filesize = int(ref_bytes_per_kbps * fmt.tbr)

        for fmt in formats:
            fmt.filesize_str = _format_filesize(fmt.filesize)
            # 重建 label：用新的 filesize_str 替换旧的大小描述
            if fmt.filesize_str:
                import re as _re2
                # 去掉旧的大小描述（如 "，约 3.2 MB"），加上新的
                base_label = _re2.sub(r'[，,]\s*约?\s*[\d.]+\s*[KMGT]?B\s*$', '', fmt.label or '').strip()
                if fmt.is_audio_only:
                    fmt.label = base_label  # 音频不在 label 里加大小
                else:
                    fmt.label = f"{base_label}，约 {fmt.filesize_str}"

        # 估算每个分P的文件大小
        if parts and len(parts) > 1 and video_duration:
            ref_fmt = next((f for f in formats if f.filesize and f.filesize > 0 and not f.is_best), None)
            if ref_fmt:
                bytes_per_sec = ref_fmt.filesize / video_duration
                for p in parts:
                    if p.duration:
                        p.filesize = int(bytes_per_sec * p.duration)
                        p.filesize_str = _format_filesize(p.filesize)

        # 提取章节信息（YouTube 等平台的视频章节标记）
        chapters = []
        raw_chapters = info.get('chapters') or []
        for ch in raw_chapters:
            chapters.append(VideoChapter(
                start_time=ch.get('start_time', 0),
                end_time=ch.get('end_time', 0),
                title=ch.get('title', '') or '',
            ))

        # 提取字幕信息
        subtitles = []
        _pref_ext = ('srt', 'vtt', 'json3', 'srv1', 'srv2', 'srv3')

        def _pick_best_ext(formats_list):
            for ext in _pref_ext:
                if any(f.get('ext') == ext for f in formats_list):
                    return ext
            return formats_list[0].get('ext', 'srt') if formats_list else 'srt'

        # 手动字幕（跳过弹幕，弹幕不是真正的字幕）
        for lang, fmts in (info.get('subtitles') or {}).items():
            if not fmts or lang == 'danmaku':
                continue
            ext = _pick_best_ext(fmts)
            name = next((f.get('name') or lang for f in fmts if f.get('name')), lang)
            subtitles.append(SubtitleTrack(lang=lang, name=name, ext=ext, is_auto=False))

        # 自动生成字幕 + YouTube 翻译字幕
        # YouTube 的 automatic_captions 包含翻译条目，如 "zh-Hans-en"（从英文翻译的中文）
        # 这些条目的 URL 带有 tlang 参数，可直接从 YouTube 服务器获取翻译结果
        auto_subs = info.get('automatic_captions') or {}
        seen_langs: set[str] = set()
        for lang, fmts in auto_subs.items():
            if not fmts:
                continue
            ext = _pick_best_ext(fmts)
            name = next((f.get('name') or lang for f in fmts if f.get('name')), lang)
            # 去重：同一语言只保留一个条目
            if lang not in seen_langs:
                seen_langs.add(lang)
                subtitles.append(SubtitleTrack(lang=lang, name=name, ext=ext, is_auto=True))

        # 提取最佳视频流 URL 用于在线播放（合并流优先，否则降级到纯视频流）
        stream_url = None
        stream_needs_audio = False
        stream_expires_at = None
        combined_fmts = [
            f for f in raw_formats
            if (f.get('vcodec', 'none') or 'none') != 'none'
            and (f.get('acodec', 'none') or 'none') != 'none'
            and f.get('url')
        ]
        if combined_fmts:
            best = max(combined_fmts, key=lambda f: f.get('height') or 0)
            stream_url = best['url']
        else:
            # DASH 降级：使用最佳纯视频流，并由前端伴随独立音频播放。
            video_only_fmts = [
                f for f in raw_formats
                if (f.get('vcodec', 'none') or 'none') != 'none'
                and (f.get('acodec', 'none') or 'none') == 'none'
                and f.get('url')
            ]
            if video_only_fmts:
                best = max(video_only_fmts, key=lambda f: f.get('height') or 0)
                stream_url = best['url']
                stream_needs_audio = bool(audio_stream_url)
        if stream_url:
            stream_expires_at = int(time.time()) + 1800

        return VideoInfo(
            title=title,
            webpage_url=info.get('webpage_url', url),
            id=info.get('id'),
            duration=video_duration,
            duration_string=info.get('duration_string'),
            thumbnail=info.get('thumbnail'),
            description=(info.get('description', '') or '')[:500],
            uploader=info.get('uploader'),
            view_count=info.get('view_count'),
            upload_date=info.get('upload_date'),
            extractor=info.get('extractor'),
            formats=formats,
            parts=parts,
            chapters=chapters,
            subtitles=subtitles,
            stream_url=stream_url,
            stream_expires_at=stream_expires_at,
            audio_stream_url=audio_stream_url,
            audio_stream_expires_at=audio_stream_expires_at,
            stream_needs_audio=stream_needs_audio,
        )

    def _download_concat_parts(self, url: str, format_id: str, task_id: str, task_dir: str,
                               selected_indices: Optional[list] = None) -> str:
        """逐P下载后用 ffmpeg concat 合并为单文件。"""
        import re as _re
        import glob as _glob
        import subprocess

        parts = _fetch_bilibili_parts(url)
        bv_match = _re.search(r'(BV\w+)', url)
        if not bv_match or not parts:
            raise Exception('无法获取分P列表')
        bvid = bv_match.group(1)

        if selected_indices:
            allowed = set(selected_indices)
            parts = [p for p in parts if p.index in allowed]
        if not parts:
            raise Exception('选中的分P不存在')

        total = len(parts)
        part_files = []
        _video_exts = {'.mp4', '.mkv', '.webm', '.flv', '.avi', '.m4v', '.mov'}

        for i, part in enumerate(parts):
            part_url = f'https://www.bilibili.com/video/{bvid}?p={part.index}'
            part_dir = os.path.join(task_dir, f'p{part.index:03d}')
            os.makedirs(part_dir, exist_ok=True)

            ydl_opts = {
                'format': format_id,
                'outtmpl': os.path.join(part_dir, '%(title).80s.%(ext)s'),
                'merge_output_format': 'mp4',
                'quiet': True,
                'no_warnings': True,
                'noplaylist': True,
                'retries': 3,
                'fragment_retries': 3,
                'concurrent_fragment_downloads': 4,
            }
            ydl_opts.update(ydl_opts_for(part_url))
            if self.ffmpeg_location:
                ydl_opts['ffmpeg_location'] = self.ffmpeg_location

            try:
                with youtube_dl(ydl_opts, part_url) as ydl:
                    ydl.extract_info(part_url, download=True)
            except Exception as e:
                raise RuntimeError(ytdlp_error_message(e)) from e

            candidates = [
                f for f in _glob.glob(os.path.join(part_dir, '*'))
                if os.path.isfile(f) and os.path.splitext(f)[1].lower() in _video_exts
            ]
            if candidates:
                part_files.append(max(candidates, key=os.path.getsize))

            queue = self._progress_queues.get(task_id)
            if queue:
                queue.put_nowait(ProgressData(
                    status='downloading',
                    percent=round((i + 1) / total * 90, 1),
                    speed=f'P{part.index}/{total}',
                ))

        if not part_files:
            raise Exception('没有成功下载任何分P')
        if len(part_files) == 1:
            return part_files[0]

        concat_list = os.path.join(task_dir, 'concat_list.txt')
        with open(concat_list, 'w', encoding='utf-8') as f:
            for pf in part_files:
                f.write(f"file '{pf}'\n")

        output_file = os.path.join(task_dir, 'merged.mp4')
        ffmpeg_bin = self.ffmpeg_location or 'ffmpeg'
        result = subprocess.run(
            [ffmpeg_bin, '-f', 'concat', '-safe', '0', '-i', concat_list,
             '-c', 'copy', output_file, '-y'],
            capture_output=True,
        )
        if result.returncode != 0:
            raise Exception('ffmpeg 合并失败: ' + result.stderr.decode(errors='replace')[-200:])
        return output_file

    def download(self, url: str, format_id: str, task_id: Optional[str] = None,
                 concat_parts: bool = False, selected_parts: Optional[list] = None) -> str:
        """下载视频，返回下载完成的文件路径。"""
        import re as _re
        if task_id is None:
            task_id = uuid.uuid4().hex[:12]

        task_dir = os.path.join(self.output_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)

        if concat_parts:
            file_path = self._download_concat_parts(url, format_id, task_id, task_dir,
                                                    selected_indices=selected_parts)
            queue = self._progress_queues.get(task_id)
            if queue:
                queue.put_nowait(ProgressData(status='completed', percent=100, file_path=file_path))
            _cleanup_downloads(self.output_dir)
            return file_path

        output_template = os.path.join(task_dir, '%(title).100s.%(ext)s')

        ydl_opts = {
            'format': format_id,
            'outtmpl': output_template,
            'progress_hooks': [self._make_progress_hook(task_id)],
            'merge_output_format': 'mp4',
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'continuedl': True,
            'retries': 3,
            'fragment_retries': 3,
            'concurrent_fragment_downloads': 4,
        }
        ydl_opts.update(ydl_opts_for(url))

        if self.ffmpeg_location:
            ydl_opts['ffmpeg_location'] = self.ffmpeg_location

        try:
            with youtube_dl(ydl_opts, url) as ydl:
                ydl.extract_info(url, download=True)
        except Exception as e:
            raise RuntimeError(ytdlp_error_message(e)) from e

        import glob as _glob
        _video_exts = {'.mp4', '.mkv', '.webm', '.flv', '.avi', '.m4v', '.mov'}
        candidates = [
            f for f in _glob.glob(os.path.join(task_dir, '*'))
            if os.path.isfile(f) and os.path.splitext(f)[1].lower() in _video_exts
        ]
        if not candidates:
            candidates = [f for f in _glob.glob(os.path.join(task_dir, '*')) if os.path.isfile(f)]
        if not candidates:
            raise Exception('下载完成但找不到输出文件')
        file_path = max(candidates, key=os.path.getsize)

        queue = self._progress_queues.get(task_id)
        if queue:
            queue.put_nowait(ProgressData(status='completed', percent=100, file_path=file_path))

        _cleanup_downloads(self.output_dir)
        return file_path
