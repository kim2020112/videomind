"""AI 视频总结模块 - 调用 DeepSeek API（Anthropic 兼容格式）生成摘要、章节大纲、思维导图。"""

import json
import os
import re
import urllib.request
from xml.etree import ElementTree

import anthropic
from dotenv import load_dotenv

# 加载 .env 配置
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

_DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/anthropic")
_DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
_DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

_MAX_SUBTITLE_CHARS = 60000


def _get_client() -> anthropic.Anthropic:
    if not _DEEPSEEK_API_KEY:
        raise ValueError("未配置 DEEPSEEK_API_KEY，请在 backend/.env 中设置")
    return anthropic.Anthropic(api_key=_DEEPSEEK_API_KEY, base_url=_DEEPSEEK_BASE_URL)


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
        return ' '.join(texts)
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


def _split_text(text: str, max_chars: int = _MAX_SUBTITLE_CHARS) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    paragraphs = text.split('\n')
    chunks, current, current_len = [], [], 0
    for para in paragraphs:
        para_len = len(para) + 1
        if current_len + para_len > max_chars and current:
            chunks.append('\n'.join(current))
            current, current_len = [para], para_len
        else:
            current.append(para)
            current_len += para_len
    if current:
        chunks.append('\n'.join(current))
    return chunks


def _build_prompt(subtitle_text: str, video_title: str = "") -> str:
    title_hint = f"视频标题：{video_title}\n\n" if video_title else ""
    return f"""你是一个专业的视频内容分析助手。请根据以下视频字幕内容，生成结构化的总结。

{title_hint}字幕内容：
---
{subtitle_text}
---

请直接输出 Markdown 格式的全面视频总结，200-500字。

要求：
1. 必须使用 ## 标题分段、**加粗**关键概念、- 列表列举要点
2. 涵盖核心观点和关键信息
3. 用中文输出
4. 只输出纯 Markdown，不要 JSON 或代码块包裹"""


def _build_mindmap_prompt(subtitle_text: str, video_title: str = "") -> str:
    title_hint = f"视频标题：{video_title}\n\n" if video_title else ""
    return f"""你是一个专业的思维导图生成助手，请将以下视频字幕内容整理为思维导图结构。

{title_hint}字幕内容：
---
{subtitle_text}
---

请使用 Markdown 标题层级格式输出：
1. # 一级标题是视频核心主题
2. ## 二级标题是主要章节/模块
3. ### 三级标题是各章节的要点
4. #### 四级标题可做更细的展开

要求：
- 每个节点的文字要简洁精炼
- 提取视频中的具体概念、技术术语、工具名称、关键人物作为节点
- 避免使用"要点1"、"其他"等无信息量标题
- 所有内容用中文输出
- 只输出 Markdown 内容，不要其他说明文字"""


def _extract_text(response) -> str:
    """从响应中提取文本内容，跳过 ThinkingBlock 等非文本 block。"""
    for block in response.content:
        if hasattr(block, 'text'):
            return block.text.strip()
    raise ValueError("API 响应中未找到文本内容")


def _call_deepseek(client: anthropic.Anthropic, prompt: str) -> dict:
    response = client.messages.create(
        model=_DEEPSEEK_MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    content = _extract_text(response)
    return {
        "summary": content,
        "chapters": [],
    }


def summarize_subtitle(subtitle_text: str, video_title: str = "") -> dict:
    """调用 DeepSeek API 生成视频总结。"""
    client = _get_client()
    chunks = _split_text(subtitle_text)

    if len(chunks) == 1:
        prompt = _build_prompt(chunks[0], video_title)
        return _call_deepseek(client, prompt)

    partial_summaries = []
    for i, chunk in enumerate(chunks):
        partial_prompt = f"请对以下视频字幕片段（第 {i+1}/{len(chunks)} 部分）生成简要摘要，100-200字：\n\n---\n{chunk}\n---\n\n直接输出摘要文本，不要输出 JSON 或其他格式。"
        resp = client.messages.create(
            model=_DEEPSEEK_MODEL,
            max_tokens=1000,
            messages=[{"role": "user", "content": partial_prompt}],
        )
        partial_summaries.append(_extract_text(resp))

    combined = '\n\n'.join(partial_summaries)
    prompt = _build_prompt(combined, video_title)
    return _call_deepseek(client, prompt)


def summarize_from_description(title: str, description: str) -> dict:
    """无字幕时，基于视频标题和简介生成基础总结。"""
    client = _get_client()
    prompt = f"""你是一个专业的视频内容分析助手。该视频没有字幕，请根据以下视频标题和简介生成内容总结。

视频标题：{title}

视频简介：
---
{description[:3000]}
---

请直接输出 Markdown 格式的内容总结，150-350字，使用 ## 标题、**加粗**关键概念、- 列表等格式。用中文输出。"""

    return _call_deepseek(client, prompt)


def stream_summarize(subtitle_text: str, video_title: str = ""):
    """流式调用 DeepSeek API，yield (event_type, data) tuple 用于 SSE。"""
    client = _get_client()
    chunks = _split_text(subtitle_text)

    if len(chunks) == 1:
        prompt = _build_prompt(chunks[0], video_title)
        yield from _stream_single(client, prompt)
    else:
        partial_summaries = []
        for i, chunk in enumerate(chunks):
            partial_prompt = f"请对以下视频字幕片段（第 {i+1}/{len(chunks)} 部分）生成简要摘要，100-200字：\n\n---\n{chunk}\n---\n\n直接输出摘要文本，不要输出 JSON 或其他格式。"
            resp = client.messages.create(
                model=_DEEPSEEK_MODEL,
                max_tokens=1000,
                messages=[{"role": "user", "content": partial_prompt}],
            )
            partial_summaries.append(_extract_text(resp))

        combined = '\n\n'.join(partial_summaries)
        prompt = _build_prompt(combined, video_title)
        yield from _stream_single(client, prompt)


def _stream_single(client: anthropic.Anthropic, prompt: str):
    """流式调用，yield SSE 事件。纯摘要模式——无思维导图分隔符。"""
    full_text = ""

    try:
        with client.messages.stream(
            model=_DEEPSEEK_MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for event in stream:
                if event.type == "content_block_start":
                    if getattr(event.content_block, 'type', None) == 'thinking':
                        pass
                    else:
                        yield ("text_start", {})
                elif event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, 'text') and delta.text:
                        full_text += delta.text
                        yield ("text", {"text": delta.text})
                elif event.type == "content_block_stop":
                    pass

        summary = full_text.strip()
        if not summary:
            summary = "AI 未能生成有效的总结内容，请重试。"

        yield ("result", {
            "summary": summary,
            "chapters": [],
        })

    except Exception as e:
        yield ("error", {"message": str(e)})


def generate_mindmap_markdown(subtitle_text: str, video_title: str = "") -> str:
    """单独调用 DeepSeek API 生成思维导图 Markdown。"""
    client = _get_client()
    chunks = _split_text(subtitle_text)

    if len(chunks) == 1:
        prompt = _build_mindmap_prompt(chunks[0], video_title)
    else:
        prompt_parts = []
        for i, chunk in enumerate(chunks):
            prompt_parts.append(f"## 第 {i+1}/{len(chunks)} 部分\n{chunk}")
        prompt = _build_mindmap_prompt('\n\n'.join(prompt_parts), video_title)

    response = client.messages.create(
        model=_DEEPSEEK_MODEL,
        max_tokens=2000,
        temperature=0.5,
        messages=[{"role": "user", "content": prompt}],
    )
    return _extract_text(response)


def _parse_json_response(content: str) -> dict:
    """从文本中提取 JSON，与 _call_deepseek 保持一致。"""
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
    if json_match:
        content = json_match.group(1).strip()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {
            "summary": content[:2000],
            "chapters": [],
            "mindmap": {"title": "视频内容", "children": []},
        }
    return {
        "summary": data.get("summary", ""),
        "chapters": data.get("chapters", []),
        "mindmap": data.get("mindmap", {"title": "视频内容", "children": []}),
    }


def stream_chat(subtitle_text: str, question: str, history: list = None):
    """流式 AI 问答，基于字幕内容回答用户问题。"""
    client = _get_client()

    history_lines = []
    if history:
        for msg in history[-10:]:
            role = "用户" if msg.get("role") == "user" else "助手"
            history_lines.append(f"{role}：{msg.get('content', '')}")
    history_text = '\n'.join(history_lines) if history_lines else "无历史对话"

    subtitle_context = subtitle_text[-80000:] if len(subtitle_text) > 80000 else subtitle_text

    prompt = f"""你是一个基于视频字幕内容的问答助手。请根据以下视频字幕内容回答用户的问题。

视频字幕：
---
{subtitle_context}
---

历史对话：
{history_text}

用户问题：{question}

请基于以上字幕内容回答问题。如果答案不在字幕中，请如实告知。用中文回答，保持简洁准确。"""

    try:
        with client.messages.stream(
            model=_DEEPSEEK_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, 'text') and delta.text:
                        yield ("text", {"text": delta.text})

    except Exception as e:
        yield ("error", {"message": str(e)})


def extract_bilibili_subtitle(url: str) -> dict | None:
    """B 站专用：通过 dm/view API 获取 CC 字幕（人工字幕 > 自动字幕）。

    返回:
        {
            "has_subtitle": bool,
            "language": str,
            "subtitle_type": "manual" | "auto",
            "segments": [{"start": float, "end": float, "text": str}, ...],
            "full_text": str,
            "text": str,  # 兼容旧接口，带时间戳的格式化文本
        }
        无字幕时返回 None
    """
    m = re.search(r'(BV[a-zA-Z0-9]+)', url)
    if not m:
        return None
    bvid = m.group(1)

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': f'https://www.bilibili.com/video/{bvid}',
        }

        # 1. 获取 aid + cid
        view_req = urllib.request.Request(
            f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}',
            headers=headers,
        )
        view_data = json.loads(urllib.request.urlopen(view_req, timeout=15).read())
        cid = view_data.get('data', {}).get('cid')
        aid = view_data.get('data', {}).get('aid')
        if not cid or not aid:
            return None

        # 2. 通过 dm/view API 获取字幕列表（type=1 返回字幕信息）
        dm_req = urllib.request.Request(
            f'https://api.bilibili.com/x/v2/dm/view?aid={aid}&oid={cid}&type=1',
            headers=headers,
        )
        dm_data = json.loads(urllib.request.urlopen(dm_req, timeout=15).read())
        subtitle_list = dm_data.get('data', {}).get('subtitle', {}).get('subtitles', [])

        if not subtitle_list:
            return None

        # 3. 选择最佳字幕：中文人工字幕 > 中文自动字幕 > 第一个
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

        # 强制 HTTPS
        if sub_url.startswith('//'):
            sub_url = 'https:' + sub_url
        if sub_url.startswith('http://'):
            sub_url = 'https://' + sub_url[7:]

        # 4. 下载字幕 JSON
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

        full_text = ' '.join(seg['text'] for seg in segments)
        # 带时间戳的格式化文本（用于前端字幕展示）
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
