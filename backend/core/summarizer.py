"""AI 视频总结模块 — 字幕清洗 + B站字幕提取 + 降级方案。

AI 调用统一委托给 core.ai_client（prompt 文件化，结构化输出）。
"""

import json
import os
import re
import urllib.request
from xml.etree import ElementTree

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from core.ai_client import summarize, generate_notes, generate_mindmap, stream_summarize, stream_generate_notes, stream_chat, _chunk_summarize


# ──── 字幕清洗 ────

def clean_subtitle_text(raw_content: str, ext: str) -> str:
    """清洗字幕文本，去除时间码和格式标记，返回纯文本。"""
    if ext == "srt":
        return _clean_srt(raw_content)
    elif ext in ("vtt", "webvtt"):
        return _clean_vtt(raw_content)
    elif ext in ("json3", "srv1", "srv2", "srv3"):
        return _clean_json_subtitle(raw_content)
    else:
        return _clean_plain_text(raw_content)


def _clean_srt(content: str) -> str:
    blocks = re.split(r'\n\s*\n', content.strip())
    texts = []
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        text_lines = [l.strip() for l in lines[2:] if l.strip()]
        if text_lines:
            texts.append(' '.join(text_lines))
    return '\n'.join(texts)


def _clean_vtt(content: str) -> str:
    lines = content.strip().split('\n')
    texts = []
    for line in lines:
        line = line.strip()
        if not line or line == 'WEBVTT' or line.startswith('NOTE') or '-->' in line:
            continue
        line = re.sub(r'<[^>]+>', '', line)
        if line and not line.isdigit():
            texts.append(line)
    return '\n'.join(texts)


def _clean_json_subtitle(content: str) -> str:
    try:
        data = json.loads(content)
        texts = []
        for event in data.get('events', []):
            for seg in event.get('segs', []):
                t = seg.get('utf8', '')
                if t and t.strip() and t.strip() != '\n':
                    texts.append(t.strip())
        return '\n'.join(texts)
    except (json.JSONDecodeError, KeyError):
        return _clean_plain_text(content)


def _clean_plain_text(content: str) -> str:
    lines = content.strip().split('\n')
    texts = []
    for line in lines:
        line = line.strip()
        if line and not re.match(r'^\d+$', line) and '-->' not in line:
            line = re.sub(r'<[^>]+>', '', line)
            if line:
                texts.append(line)
    return '\n'.join(texts)


def extract_subtitle_segments(raw_content: str, ext: str) -> list[dict]:
    """从原始字幕内容中提取带时间信息的 segments。
    返回 [{start: float, end: float, text: str}, ...]
    """
    if ext == "srt":
        return _extract_srt_segments(raw_content)
    elif ext in ("vtt", "webvtt"):
        return _extract_vtt_segments(raw_content)
    elif ext in ("json3", "srv1", "srv2", "srv3"):
        return _extract_json_segments(raw_content)
    return []


def _parse_ts(ts: str) -> float:
    """解析 SRT/VTT 时间戳为秒数。支持 '00:01:23,456' 和 '00:01:23.456'。"""
    ts = ts.strip().replace(',', '.')
    parts = ts.split(':')
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return 0.0


def _extract_srt_segments(content: str) -> list[dict]:
    blocks = re.split(r'\n\s*\n', content.strip())
    segments = []
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        ts_match = re.match(r'([\d:,.]+)\s*-->\s*([\d:,.]+)', lines[1])
        if not ts_match:
            continue
        start = _parse_ts(ts_match.group(1))
        end = _parse_ts(ts_match.group(2))
        text = ' '.join(l.strip() for l in lines[2:] if l.strip())
        text = re.sub(r'<[^>]+>', '', text)
        if text:
            segments.append({'start': start, 'end': end, 'text': text})
    return segments


def _extract_vtt_segments(content: str) -> list[dict]:
    lines = content.strip().split('\n')
    segments = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        ts_match = re.match(r'([\d:,.]+)\s*-->\s*([\d:,.]+)', line)
        if ts_match:
            start = _parse_ts(ts_match.group(1))
            end = _parse_ts(ts_match.group(2))
            i += 1
            text_lines = []
            while i < len(lines):
                l = lines[i].strip()
                if not l or '-->' in l:
                    break
                l = re.sub(r'<[^>]+>', '', l)
                if l and not l.isdigit():
                    text_lines.append(l)
                i += 1
            text = ' '.join(text_lines)
            if text:
                segments.append({'start': start, 'end': end, 'text': text})
        else:
            i += 1
    return segments


def _extract_json_segments(content: str) -> list[dict]:
    try:
        data = json.loads(content)
        segments = []
        for event in data.get('events', []):
            t_start = event.get('tStartMs', 0) / 1000.0
            duration = event.get('dDurationMs', 0) / 1000.0
            text_parts = []
            for seg in event.get('segs', []):
                t = seg.get('utf8', '')
                if t and t.strip() and t.strip() != '\n':
                    text_parts.append(t.strip())
            text = ' '.join(text_parts)
            if text:
                segments.append({'start': t_start, 'end': t_start + duration, 'text': text})
        return segments
    except (json.JSONDecodeError, KeyError):
        return []


def _clean_danmaku_xml(content: str) -> str:
    """清洗弹幕 XML，提取弹幕文本和时间戳。"""
    try:
        root = ElementTree.fromstring(content)
        entries = []
        for d in root.iter('d'):
            raw = d.get('p', '')
            parts = raw.split(',')
            time_val = float(parts[0]) if parts else 0
            text = (d.text or '').strip()
            if text:
                minutes = int(time_val // 60)
                seconds = int(time_val % 60)
                entries.append((time_val, f"[{minutes:02d}:{seconds:02d}] {text}"))
        entries.sort(key=lambda x: x[0])
        return '\n'.join(text for _, text in entries)
    except Exception:
        return _clean_plain_text(content)


# ──── 降级方案 ────

def summarize_from_description(title: str, description: str) -> dict:
    """无字幕时，基于视频标题和简介生成基础总结。"""
    subtitle_text = f"视频标题：{title}\n\n视频简介：\n{description[:3000]}"
    return summarize(subtitle_text, title)


# ──── B 站 CC 字幕提取 ────

def extract_bilibili_subtitle_by_cid(bvid: str, cid: int, aid: int = None) -> dict | None:
    """获取B站指定分P的CC字幕（人工字幕 > 自动字幕）。

    Args:
        bvid: 视频 BV 号
        cid: 分P的 cid
        aid: 视频 aid（可选，未提供时自动获取）

    返回格式同 extract_bilibili_subtitle。
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': f'https://www.bilibili.com/video/{bvid}',
        }

        if not aid:
            view_req = urllib.request.Request(
                f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}',
                headers=headers,
            )
            view_data = json.loads(urllib.request.urlopen(view_req, timeout=15).read())
            aid = view_data.get('data', {}).get('aid')
            if not aid:
                return None

        dm_req = urllib.request.Request(
            f'https://api.bilibili.com/x/v2/dm/view?aid={aid}&oid={cid}&type=1',
            headers=headers,
        )
        dm_data = json.loads(urllib.request.urlopen(dm_req, timeout=15).read())
        subtitle_list = dm_data.get('data', {}).get('subtitle', {}).get('subtitles') or []

        if not subtitle_list:
            return None

        best = subtitle_list[0]
        for s in subtitle_list:
            lan = s.get('lan', '')
            if lan in ('zh', 'zh-Hans'):
                if not lan.startswith('ai-'):
                    best = s
                    break
                best = s

        sub_type = 'auto' if (best.get('lan', '') or '').startswith('ai-') else 'manual'
        sub_url = best.get('subtitle_url', '')
        if not sub_url:
            return None

        if sub_url.startswith('//'):
            sub_url = 'https:' + sub_url
        if sub_url.startswith('http://'):
            sub_url = 'https://' + sub_url[7:]

        sub_req = urllib.request.Request(sub_url, headers=headers)
        sub_json = json.loads(urllib.request.urlopen(sub_req, timeout=15).read())
        body = sub_json.get('body', [])

        segments = []
        for item in body:
            content = (item.get('content', '') or '').strip()
            if not content:
                continue
            segments.append({
                'start': round(item.get('from', 0), 2),
                'end': round(item.get('to', 0), 2),
                'text': content,
            })

        full_text = '\n'.join(seg['text'] for seg in segments)
        formatted_lines = []
        for seg in segments:
            mm = int(seg['start'] // 60)
            ss = int(seg['start'] % 60)
            formatted_lines.append(f"[{mm:02d}:{ss:02d}] {seg['text']}")

        return {
            'has_subtitle': True,
            'language': best.get('lan', 'zh'),
            'subtitle_type': sub_type,
            'segments': segments,
            'full_text': full_text,
            'text': '\n'.join(formatted_lines),
        }

    except Exception:
        return None


def extract_bilibili_subtitle(url: str) -> dict | None:
    """B 站专用：通过 dm/view API 获取 CC 字幕（P1）。"""
    m = re.search(r'(BV[a-zA-Z0-9]+)', url)
    if not m:
        return None
    bvid = m.group(1)

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': f'https://www.bilibili.com/video/{bvid}',
        }
        view_req = urllib.request.Request(
            f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}',
            headers=headers,
        )
        view_data = json.loads(urllib.request.urlopen(view_req, timeout=15).read())
        cid = view_data.get('data', {}).get('cid')
        aid = view_data.get('data', {}).get('aid')
        if not cid or not aid:
            return None

        return extract_bilibili_subtitle_by_cid(bvid, cid, aid)

    except Exception:
        return None


# ──── 别名（兼容旧 import） ────

summarize_subtitle = summarize
