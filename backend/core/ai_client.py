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


# ──── 非流式 API ────

def summarize(subtitle_text: str, video_title: str = "") -> dict:
    """生成 AI 摘要（Markdown）。长视频自动分片。"""
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
    return {"summary": text, "chapters": [], "key_points": []}


def generate_notes(subtitle_text: str, video_title: str = "") -> dict:
    """生成结构化学习笔记（Markdown）。"""
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
    """流式生成 AI 摘要。yield (event_type, data) 兼容现有 SSE。"""
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

        summary_text = full_text.strip() or "AI 未能生成有效的总结内容，请重试。"
        yield ("result", {"summary": summary_text})

    except Exception as e:
        yield ("error", {"message": str(e)})


def stream_generate_notes(subtitle_text: str, video_title: str = ""):
    """流式生成学习笔记。yield (event_type, data)。"""
    client = _get_client()
    prompt = _load_prompt("notes").format(
        video_title=f"视频标题：{video_title}\n\n" if video_title else "",
        subtitle_text=_chunk_summarize(subtitle_text, video_title),
    )

    try:
        with client.messages.stream(
            model=AI_MODEL, max_tokens=6000,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "text") and delta.text:
                        yield ("notes_text", {"text": delta.text})
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
    """流式生成学习卡片。"""
    client = _get_client()
    prompt = _load_prompt("flashcard").format(
        video_title=video_title,
        content_summary=content_summary[:60000],
    )

    try:
        with client.messages.stream(
            model=AI_MODEL, max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "text") and delta.text:
                        yield ("flashcard_text", {"text": delta.text})
    except Exception as e:
        yield ("error", {"message": str(e)})
