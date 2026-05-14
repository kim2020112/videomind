"""统一 AI API 客户端 — DeepSeek 为主，OpenAI 兼容协议可切换。"""

import anthropic
from config import AI_API_KEY, AI_BASE_URL, AI_MODEL


def _get_client() -> anthropic.Anthropic:
    if not AI_API_KEY:
        raise ValueError("未配置 AI_API_KEY，请在 backend/.env 中设置")
    return anthropic.Anthropic(api_key=AI_API_KEY, base_url=AI_BASE_URL)


def _extract_text(response) -> str:
    for block in response.content:
        if hasattr(block, "text"):
            return block.text.strip()
    raise ValueError("API 响应中未找到文本内容")


MAX_SUBTITLE_CHARS = 60000


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


def summarize(subtitle_text: str, video_title: str = "") -> str:
    client = _get_client()
    chunks = _split_text(subtitle_text)

    if len(chunks) > 1:
        partials = []
        for i, chunk in enumerate(chunks):
            prompt = f"请对以下视频字幕片段（第 {i+1}/{len(chunks)} 部分）生成简要摘要，100-200字：\n\n---\n{chunk}\n---"
            resp = client.messages.create(
                model=AI_MODEL, max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            partials.append(_extract_text(resp))
        subtitle_text = "\n\n".join(partials)

    title_hint = f"视频标题：{video_title}\n\n" if video_title else ""
    prompt = f"""你是一个专业的视频内容分析助手。请根据以下视频字幕内容，生成结构化的总结。

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

    resp = client.messages.create(
        model=AI_MODEL, max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    return _extract_text(resp)


def generate_mindmap(subtitle_text: str, video_title: str = "") -> str:
    client = _get_client()
    chunks = _split_text(subtitle_text)
    if len(chunks) > 1:
        parts = [f"## 第 {i+1}/{len(chunks)} 部分\n{c}" for i, c in enumerate(chunks)]
        subtitle_text = "\n\n".join(parts)

    title_hint = f"视频标题：{video_title}\n\n" if video_title else ""
    prompt = f"""你是一个专业的思维导图生成助手，请将以下视频字幕内容整理为思维导图结构。

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
- 提取视频中的具体概念、技术术语、工具名称作为节点
- 避免使用"要点1"、"其他"等无信息量标题
- 所有内容用中文输出
- 只输出 Markdown 内容"""

    resp = client.messages.create(
        model=AI_MODEL, max_tokens=2000, temperature=0.5,
        messages=[{"role": "user", "content": prompt}],
    )
    return _extract_text(resp)


def generate_notes(subtitle_text: str, video_title: str = "") -> str:
    client = _get_client()
    chunks = _split_text(subtitle_text)
    if len(chunks) > 1:
        parts = [f"## 第 {i+1}/{len(chunks)} 部分\n{c}" for i, c in enumerate(chunks)]
        subtitle_text = "\n\n".join(parts)

    title_hint = f"视频标题：{video_title}\n\n" if video_title else ""
    prompt = f"""你是一个专业的学习笔记生成助手。请将以下视频内容整理为结构化的 Markdown 学习笔记。

{title_hint}字幕内容：
---
{subtitle_text}
---

要求：
1. 使用 ## 和 ### 标题分层组织
2. 关键概念用 **加粗**
3. 步骤/流程用有序列表
4. 要点用无序列表
5. 代码/命令用 `行内代码` 或代码块
6. 重要提示用 > 引用块
7. 适当使用 emoji 标记类别（💡提示 ⚠️注意 ✅要点 📌重点）
8. 笔记应该是可独立阅读的，不依赖视频
9. 300-800字，信息密度高
10. 用中文输出
11. 只输出纯 Markdown，不要 JSON 或代码块包裹"""

    resp = client.messages.create(
        model=AI_MODEL, max_tokens=4000,
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


def stream_generate_notes(subtitle_text: str, video_title: str = ""):
    """流式生成学习笔记，yield (event_type, data)。"""
    client = _get_client()
    chunks = _split_text(subtitle_text)
    if len(chunks) > 1:
        parts = [f"## 第 {i+1}/{len(chunks)} 部分\n{c}" for i, c in enumerate(chunks)]
        subtitle_text = "\n\n".join(parts)

    title_hint = f"视频标题：{video_title}\n\n" if video_title else ""
    prompt = f"""你是一个专业的学习笔记生成助手。请将以下视频内容整理为结构化的 Markdown 学习笔记。

{title_hint}字幕内容：
---
{subtitle_text}
---

要求：
1. 使用 ## 和 ### 标题分层组织
2. 关键概念用 **加粗**
3. 步骤/流程用有序列表
4. 要点用无序列表
5. 代码/命令用 `行内代码` 或代码块
6. 重要提示用 > 引用块
7. 适当使用 emoji 标记类别（💡提示 ⚠️注意 ✅要点 📌重点）
8. 笔记应该是可独立阅读的，不依赖视频
9. 300-800字，信息密度高
10. 用中文输出
11. 只输出纯 Markdown，不要 JSON 或代码块包裹"""

    try:
        with client.messages.stream(
            model=AI_MODEL, max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "text") and delta.text:
                        yield ("notes_text", {"text": delta.text})
    except Exception as e:
        yield ("error", {"message": str(e)})


def stream_rag_answer(question: str, context_chunks: list[str], history: list = None):
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
