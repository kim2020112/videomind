"""统一 AI API 客户端 — 支持多 provider，prompt 文件化，结构化 JSON 输出。"""

import json
import re

import anthropic
from config import AI_API_KEY, AI_BASE_URL, AI_MODEL, AI_PROVIDER, PROMPT_VERSION, BASE_DIR

MAX_SUBTITLE_CHARS = 60000
JSON_BLOCK_RE = re.compile(r'```(?:json)?\s*\n?(.*?)\n?```', re.DOTALL)


# ──── Prompt 加载 ────

def _load_prompt(name: str) -> str:
    """从 prompts/{name}/v{PROMPT_VERSION}.txt 加载 prompt 模板。"""
    path = BASE_DIR / "prompts" / name / f"v{PROMPT_VERSION}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt 文件不存在: {path}")
    return path.read_text(encoding="utf-8")


# ──── AI Client ────

def _get_client() -> anthropic.Anthropic:
    if not AI_API_KEY:
        raise ValueError("未配置 AI_API_KEY，请在 backend/.env 中设置")
    return anthropic.Anthropic(api_key=AI_API_KEY, base_url=AI_BASE_URL)


def _extract_text(response) -> str:
    for block in response.content:
        if hasattr(block, "text"):
            return block.text.strip()
    raise ValueError("API 响应中未找到文本内容")


# ──── 文本分片 ────

def _split_text(text: str, max_chars: int = MAX_SUBTITLE_CHARS) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    paragraphs = text.split("\n")
    chunks, current, current_len = [], [], 0
    for para in paragraphs:
        para_len = len(para) + 1
        if current_len + para_len > max_chars and current:
            chunks.append("\n".join(current))
            current, current_len = [para], para_len
        else:
            current.append(para)
            current_len += para_len
    if current:
        chunks.append("\n".join(current))
    return chunks


# ──── 结构化 JSON 解析 ────

def _parse_json_response(content: str) -> dict:
    """从 AI 响应中提取 JSON。支持代码块包裹和裸 JSON。"""
    # 尝试提取 ```json ... ``` 中的内容
    m = JSON_BLOCK_RE.search(content)
    if m:
        content = m.group(1).strip()
    # 尝试找到第一个 { 到最后一个 }
    start = content.find('{')
    end = content.rfind('}')
    if start != -1 and end != -1 and end > start:
        content = content[start:end + 1]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # 返回原始文本作为 summary
        return {"summary": content, "notes": "", "key_points": [], "code_blocks": [], "flashcards": [], "one_liner": "", "continue_learning": []}


def _parse_json_or_fallback(content: str) -> dict:
    """解析 JSON 响应，失败时返回 {{raw_text: content}} 的 fallback。"""
    parsed = _parse_json_response(content)
    if "raw_text" not in parsed and len(parsed) <= 2 and "summary" in parsed:
        # 这是旧版 fallback 格式，保留原始文本
        return {"raw_text": content, **parsed}
    return parsed


# ──── Chunk Summary Pipeline（长视频） ────

def _chunk_summarize(subtitle_text: str, video_title: str) -> str:
    """长视频分片摘要 → 合并。返回合并后的摘要文本。"""
    chunks = _split_text(subtitle_text)
    if len(chunks) == 1:
        return chunks[0]

    client = _get_client()
    partials = []
    for i, chunk in enumerate(chunks):
        resp = client.messages.create(
            model=AI_MODEL, max_tokens=1000,
            messages=[{"role": "user", "content": f"请对以下视频字幕片段（第 {i+1}/{len(chunks)} 部分）生成简要摘要，100-200字：\n\n---\n{chunk}\n---"}],
        )
        partials.append(_extract_text(resp))
    return "\n\n".join(partials)


def stream_chunk_summaries(subtitle_text: str, video_title: str = ""):
    """长视频分片摘要生成器 — 首片优先。

    yield 事件:
      ("first_chunk_ready", {"text": str, "total": int})
          首片完成（详细摘要），可立即开始主摘要流式输出
      ("chunk_progress", {"index": int, "total": int})
          每片完成时通知进度
      ("all_chunks_ready", {"text": str})
          全部完成，合并文本用于完整摘要
    """
    chunks = _split_text(subtitle_text)
    total = len(chunks)

    if total == 1:
        yield ("all_chunks_ready", {"text": chunks[0]})
        return

    client = _get_client()
    partials = [None] * total

    for i, chunk in enumerate(chunks):
        if i == 0:
            prompt = f"请对以下视频字幕片段（第 1/{total} 部分，约占视频前 {100//total}%）生成详细摘要，200-300 字，并提取 2-3 个核心概念：\n\n---\n{chunk}\n---"
            max_tok = 1500
        else:
            prompt = f"请对以下视频字幕片段（第 {i+1}/{total} 部分）生成简要摘要，100-150 字：\n\n---\n{chunk}\n---"
            max_tok = 600

        resp = client.messages.create(
            model=AI_MODEL, max_tokens=max_tok,
            messages=[{"role": "user", "content": prompt}],
        )
        partials[i] = _extract_text(resp)

        if i == 0:
            yield ("first_chunk_ready", {"text": partials[0], "total": total})
        yield ("chunk_progress", {"index": i, "total": total})

    yield ("all_chunks_ready", {"text": "\n\n".join(partials)})


# ──── 非流式 API ────

def summarize(subtitle_text: str, video_title: str = "") -> dict:
    """生成 AI 摘要。v2 prompt 输出 JSON 时自动解析为结构化数据。"""
    client = _get_client()
    prompt = _load_prompt("summary").format(
        video_title=f"视频标题：{video_title}\n\n" if video_title else "",
        subtitle_text=_chunk_summarize(subtitle_text, video_title),
    )
    resp = client.messages.create(
        model=AI_MODEL, max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = _extract_text(resp)
    parsed = _parse_json_or_fallback(text)
    if "overview" in parsed or "key_points" in parsed:
        return {"summary": parsed.get("overview", text), "structured": parsed, "chapters": [], "key_points": parsed.get("key_points", [])}
    return {"summary": text, "chapters": [], "key_points": []}


def generate_notes(subtitle_text: str, video_title: str = "") -> dict:
    """生成结构化学习笔记。v2 prompt 输出 JSON 时自动解析。"""
    client = _get_client()
    prompt = _load_prompt("notes").format(
        video_title=f"视频标题：{video_title}\n\n" if video_title else "",
        subtitle_text=_chunk_summarize(subtitle_text, video_title),
    )
    resp = client.messages.create(
        model=AI_MODEL, max_tokens=6000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = _extract_text(resp)
    parsed = _parse_json_or_fallback(text)
    if "sections" in parsed:
        return {"notes": text, "sections": parsed["sections"], "key_points": [], "flashcards": []}
    return {"notes": text, "key_points": [], "flashcards": []}


def generate_mindmap(subtitle_text: str, video_title: str = "") -> str:
    """生成思维导图 Markdown。"""
    client = _get_client()
    prompt = _load_prompt("mindmap").format(
        video_title=f"视频标题：{video_title}\n\n" if video_title else "",
        subtitle_text=_chunk_summarize(subtitle_text, video_title),
    )
    resp = client.messages.create(
        model=AI_MODEL, max_tokens=2000, temperature=0.5,
        messages=[{"role": "user", "content": prompt}],
    )
    return _extract_text(resp)


def rag_answer(question: str, context_chunks: list[str], history: list = None) -> str:
    client = _get_client()
    context = "\n\n---\n\n".join(context_chunks)
    history_text = ""
    if history:
        lines = []
        for msg in history[-10:]:
            role = "用户" if msg.get("role") == "user" else "助手"
            lines.append(f"{role}：{msg.get('content', '')}")
        history_text = "\n历史对话：\n" + "\n".join(lines) + "\n"

    prompt = f"""你是一个基于视频知识库的问答助手。请根据以下检索到的内容回答用户问题。

相关内容：
---
{context}
---
{history_text}
用户问题：{question}

要求：
- 基于提供的内容回答，如果内容中没有相关信息请如实告知
- 用中文回答，保持简洁准确
- 使用 Markdown 格式"""

    resp = client.messages.create(
        model=AI_MODEL, max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return _extract_text(resp)


# ──── 字幕校正 ────

def correct_subtitle(subtitle_text: str, video_title: str = "", video_description: str = "") -> str:
    """AI 校正 Whisper 转录文本（修正同音错字、专有名词等）。
    失败时返回原始文本，保证流程不中断。"""
    from config import SUBTITLE_CORRECTION_ENABLED, SUBTITLE_CORRECTION_MAX_CHARS

    if not SUBTITLE_CORRECTION_ENABLED:
        return subtitle_text

    client = _get_client()
    truncated = subtitle_text[:SUBTITLE_CORRECTION_MAX_CHARS]
    desc = (video_description or "")[:500]

    prompt = _load_prompt("subtitle_correction").format(
        video_title=video_title or "（无标题）",
        video_description=desc or "（无简介）",
        subtitle_text=truncated,
    )

    try:
        resp = client.messages.create(
            model=AI_MODEL, max_tokens=min(len(truncated) * 2, 16000),
            temperature=0.1,
            messages=[{"role": "user", "content": prompt}],
        )
        corrected = _extract_text(resp)

        if len(corrected.strip()) < len(truncated.strip()) * 0.3:
            raise ValueError(f"校正后文本异常短 ({len(corrected)} vs {len(truncated)})")

        if len(subtitle_text) > SUBTITLE_CORRECTION_MAX_CHARS:
            corrected += "\n" + subtitle_text[SUBTITLE_CORRECTION_MAX_CHARS:]

        return corrected
    except Exception as e:
        print(f"[SubtitleCorrection] 校正失败，使用原始文本: {e}")
        return subtitle_text


# ──── 流式 API ────

def stream_summarize(subtitle_text: str, video_title: str = ""):
    """流式生成 AI 摘要。yield (event_type, data) 兼容现有 SSE。
    v2 prompt 输出 JSON 时自动解析为结构化数据。"""
    client = _get_client()
    prompt = _load_prompt("summary").format(
        video_title=f"视频标题：{video_title}\n\n" if video_title else "",
        subtitle_text=_chunk_summarize(subtitle_text, video_title),
    )
    full_text = ""

    try:
        with client.messages.stream(
            model=AI_MODEL, max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "text") and delta.text:
                        full_text += delta.text
                        yield ("text", {"text": delta.text})

        full_text = full_text.strip() or "AI 未能生成有效的总结内容，请重试。"
        parsed = _parse_json_or_fallback(full_text)
        # 从结构化数据中提取纯文本摘要（用于前端兼容）
        if "overview" in parsed:
            summary_text = parsed.get("overview", full_text)
        elif "summary" in parsed:
            summary_text = parsed["summary"]
        else:
            summary_text = full_text
        yield ("result", {"summary": summary_text, "structured": parsed})

    except Exception as e:
        yield ("error", {"message": str(e)})


def stream_generate_notes(subtitle_text: str, video_title: str = ""):
    """流式生成学习笔记。v2 prompt 输出 JSON 时自动解析为结构化数据。"""
    client = _get_client()
    prompt = _load_prompt("notes").format(
        video_title=f"视频标题：{video_title}\n\n" if video_title else "",
        subtitle_text=_chunk_summarize(subtitle_text, video_title),
    )
    full_text = ""

    try:
        with client.messages.stream(
            model=AI_MODEL, max_tokens=6000,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "text") and delta.text:
                        full_text += delta.text
                        yield ("notes_text", {"text": delta.text})

        full_text = full_text.strip()
        if not full_text:
            return
        parsed = _parse_json_or_fallback(full_text)
        if "sections" in parsed:
            yield ("notes_structured", {"sections": parsed["sections"]})
    except Exception as e:
        yield ("error", {"message": str(e)})


def stream_chat(subtitle_text: str, question: str, history: list = None):
    """流式 AI 问答。"""
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
            model=AI_MODEL, max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "text") and delta.text:
                        yield ("text", {"text": delta.text})
    except Exception as e:
        yield ("error", {"message": str(e)})


def stream_rag_answer(question: str, context_chunks: list[str], history: list = None):
    """流式 RAG 问答。"""
    client = _get_client()
    context = "\n\n---\n\n".join(context_chunks)
    prompt = f"""你是一个基于视频知识库的问答助手。

相关内容：
---
{context}
---

用户问题：{question}

基于提供的内容回答，用中文，使用 Markdown 格式。"""

    try:
        with client.messages.stream(
            model=AI_MODEL, max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "text") and delta.text:
                        yield ("text", {"text": delta.text})
    except Exception as e:
        yield ("error", {"message": str(e)})


def stream_flashcards(content_summary: str, video_title: str = ""):
    """流式生成学习卡片。v2 prompt 输出 JSON 时自动解析为结构化卡片。"""
    client = _get_client()
    prompt = _load_prompt("flashcard").format(
        video_title=video_title,
        content_summary=content_summary[:60000],
    )
    full_text = ""

    try:
        with client.messages.stream(
            model=AI_MODEL, max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "text") and delta.text:
                        full_text += delta.text
                        yield ("flashcard_text", {"text": delta.text})

        parsed = _parse_json_or_fallback(full_text.strip())
        if "cards" in parsed:
            yield ("flashcards", parsed["cards"])
        elif "flashcards" in parsed:
            yield ("flashcards", parsed["flashcards"])
        else:
            yield ("flashcards", [])
    except Exception as e:
        yield ("error", {"message": str(e)})


def _parse_segments_from_text(subtitle_text: str) -> list[dict]:
    """从带 [MM:SS] 时间戳的字幕文本中解析出 segments。"""
    segments = []
    for line in subtitle_text.split('\n'):
        line = line.strip()
        if not line:
            continue
        m = re.match(r'\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]\s*(.*)', line)
        if m:
            mm, ss = int(m.group(1)), int(m.group(2))
            extra = int(m.group(3)) if m.group(3) else 0
            start = mm * 60 + ss + extra
            text = m.group(4).strip()
            if text:
                segments.append({'start': start, 'text': text})
    return segments


def inject_notes_timestamps(notes_md: str, subtitle_text: str) -> str:
    """为笔记 section 标题注入字幕时间点。

    对没有 [MM:SS] 的 ## 标题，从 section 内容中提取前 100 字，
    与字幕 segments 做文本匹配，找到最相关的 segment 并注入其 start 时间。
    """
    if not notes_md or not subtitle_text:
        return notes_md

    segments = _parse_segments_from_text(subtitle_text)
    if not segments:
        return notes_md

    lines = notes_md.split('\n')
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # 检测 ## 标题行
        if re.match(r'^#{1,3}\s+', line) and not re.search(r'\[\d{1,2}:\d{2}(?::\d{2})?\]', line):
            # 提取标题文本（去掉 # 前缀）
            heading = re.sub(r'^#{1,3}\s+', '', line).strip()
            # 收集该 section 的内容（直到下一个标题或文件结尾）
            content_lines = []
            j = i + 1
            while j < len(lines) and not re.match(r'^#{1,3}\s+', lines[j]):
                if lines[j].strip():
                    content_lines.append(lines[j].strip())
                j += 1
            body_text = ' '.join(content_lines)[:200]

            # 在 segments 中找最佳匹配
            best_ts = _find_best_timestamp(heading, body_text, segments)
            if best_ts is not None:
                mm = int(best_ts // 60)
                ss = int(best_ts % 60)
                line = f"{line} [{mm:02d}:{ss:02d}]"

        result.append(line)
        i += 1

    return '\n'.join(result)


def _longest_common_substr_len(a: str, b: str) -> int:
    """最长公共子串长度。"""
    if not a or not b:
        return 0
    max_len = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i+k] == b[j+k]:
                k += 1
            if k > max_len:
                max_len = k
    return max_len


def _find_best_timestamp(heading: str, body: str, segments: list[dict]) -> float | None:
    """在 segments 中找到与 heading+body 最相关的 segment，返回其 start 时间。

    优先用 heading 做长子串匹配（精确），其次用 body 做 bigram 匹配（模糊）。
    """
    if not segments:
        return None

    clean_heading = heading.replace(' ', '')
    clean_body = body.replace(' ', '')

    best_score = 0.0
    best_start = None

    for seg in segments:
        seg_text = seg.get('text', '')
        if not seg_text:
            continue
        clean_seg = seg_text.replace(' ', '')
        if not clean_seg:
            continue

        # 策略1：heading 长子串匹配（权重高）
        lcs = _longest_common_substr_len(clean_heading, clean_seg)
        heading_score = lcs / min(len(clean_heading), len(clean_seg)) if min(len(clean_heading), len(clean_seg)) > 0 else 0

        # 策略2：body bigram 匹配（补充）
        body_score = 0.0
        if clean_body and len(clean_body) >= 2:
            body_bigrams = {clean_body[i:i+2] for i in range(len(clean_body) - 1)}
            seg_bigrams = {clean_seg[i:i+2] for i in range(len(clean_seg) - 1)}
            if body_bigrams and seg_bigrams:
                overlap = len(body_bigrams & seg_bigrams)
                body_score = overlap / min(len(body_bigrams), len(seg_bigrams))

        score = max(heading_score * 1.5, body_score)  # heading 匹配加权
        if score > best_score:
            best_score = score
            best_start = seg.get('start')

    return best_start if best_score > 0.15 else None
