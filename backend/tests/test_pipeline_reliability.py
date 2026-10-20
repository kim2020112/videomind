import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from api import stream_routes
from core import ai_client
from core.pipeline import PipelineEvent
from core.text_client import TextClient, _MessagesFacade
from config import AI_REQUEST_TIMEOUT


def test_nested_json_preserves_outer_summary_and_sections():
    payload = {"overview": "summary", "key_points": ["one"], "sections": [{"title": "notes"}]}
    assert ai_client._parse_json_response('```json\n' + json.dumps(payload) + '\n```') == payload
    assert ai_client._parse_json_response('Result: ' + json.dumps(payload)) == payload
    assert ai_client._parse_json_response('[{"question":"Q", "answer":"A"}]') == [{"question": "Q", "answer": "A"}]


def test_single_line_transcript_is_split_without_losing_content():
    text = "x" * 150001
    chunks = ai_client._split_text(text)
    assert len(chunks) == 3
    assert max(map(len, chunks)) <= ai_client.MAX_SUBTITLE_CHARS
    assert ''.join(chunks) == text


def test_qa_pair_shapes_are_normalized_not_dropped():
    from core.ai_client import _normalize_qa_pairs, _parse_json_response
    # 实测缺陷：模型在 JSON 字符串值内输出未转义的中文引号
    broken = '[{"question": "什么是"问答赞"？", "answer": "先问后"赞美"，循环。"}]'
    parsed = _parse_json_response(broken)
    pairs = _normalize_qa_pairs(parsed)
    assert len(pairs) == 1
    assert "问答赞" in pairs[0]["question"]
    assert "赞美" in pairs[0]["answer"]
    from core.ai_client import _normalize_qa_pairs
    # 对象包裹（此前被静默丢弃成空数组）
    wrapped = {"qa_pairs": [{"question": "Q", "answer": "A"}]}
    assert _normalize_qa_pairs(wrapped) == [{"question": "Q", "answer": "A"}]
    assert _normalize_qa_pairs({"questions": [{"question": "Q", "answer": "A"}]}) == [
        {"question": "Q", "answer": "A"}]
    # 字段大小写变体
    assert _normalize_qa_pairs([{"Question": "Q", "Answer": "A"}]) == [
        {"question": "Q", "answer": "A"}]
    # 非法条目过滤
    assert _normalize_qa_pairs([{"question": "只有问题"}, "str", 1]) == []
    # 裸数组保持
    assert _normalize_qa_pairs([{"question": "Q", "answer": "A"}]) == [
        {"question": "Q", "answer": "A"}]


def test_effective_speech_chars_ignores_music_and_timestamps():
    from core.ai_client import effective_speech_chars
    music_only = "[00:07] ♪♫ [00:39] ♪♪ [01:02] ♪♫♬"
    assert effective_speech_chars(music_only) < 20
    real_speech = "[00:01] 大家好，这期视频我们来聊聊相机对焦技术的演进。[00:12] 自动对焦开始普及。"
    assert effective_speech_chars(real_speech) >= 25


def test_all_prompt_templates_are_formattable():
    """提示词里出现未转义花括号会让 .format() 抛 KeyError，整条产物线静默失败。"""
    from core.ai_client import _load_prompt
    for name in ("summary", "notes", "mindmap", "qanda", "subtitle_correction"):
        template = _load_prompt(name)
        template.format(video_title="T", subtitle_text="S", video_description="D", content_summary="C")


def test_sentinel_summary_is_rejected_by_validation():
    from core.generation_commit import InvalidGenerationResult, validate_summary_result
    import pytest
    with pytest.raises(InvalidGenerationResult):
        validate_summary_result({"summary": "AI 未能生成有效的总结内容，请重试。"})
    # 正常摘要仍通过
    validate_summary_result({"summary": "## 概述\n内容"})


def test_fetch_subtitle_refresh_skips_stale_db_cache(monkeypatch):
    """force 重新生成必须跳出坏字幕缓存（如 B 站 AI 字幕跨视频错配）。"""
    import asyncio
    from types import SimpleNamespace
    from core.pipeline import subtitle as subtitle_mod

    info = SimpleNamespace(title="t", webpage_url="https://www.bilibili.com/video/BV1x",
                           extractor="bilibili", id="BV1x", parts=[], subtitles=[])
    monkeypatch.setattr(subtitle_mod, "get_subtitle_from_db",
                        lambda url: {"full_text": "[00:01] 坏字幕内容带时间戳。" * 8, "source": "bilibili_cc",
                                     "language": "ai-zh", "segments": []})
    monkeypatch.setattr(subtitle_mod, "try_get_bilibili_cc_subtitle", lambda url, info=None:
                        {"has_subtitle": True, "text": "正确的字幕内容。" * 10, "language": "zh"})
    monkeypatch.setattr(subtitle_mod, "is_bilibili_video", lambda url, info=None: True)

    # 默认：命中坏缓存
    text, source, lang = asyncio.run(subtitle_mod.fetch_subtitle(
        "https://www.bilibili.com/video/BV1x", info))
    assert "坏字幕" in text

    # refresh=True：跳过缓存，重新获取
    text, source, lang = asyncio.run(subtitle_mod.fetch_subtitle(
        "https://www.bilibili.com/video/BV1x", info, refresh=True))
    assert "正确的字幕" in text
    assert source == "bilibili_cc"


def test_thin_subtitle_is_rejected_before_generation():
    from types import SimpleNamespace
    from core import background_pipeline
    from core.generation_commit import InvalidGenerationResult

    job = {"task_id": "t1", "user_id": 1, "guest_id": None}
    info = SimpleNamespace(title="t", extractor="bilibili", id="BV1")
    music_only = "[00:07] ♪♫ [00:39] ♪♪ " * 30
    with pytest.raises(InvalidGenerationResult):
        background_pipeline.generate_full_from_subtitle(
            job, info=info, canonical_url="https://b23.tv/x", subtitle_text=music_only,
            subtitle_source="bilibili_cc", subtitle_language="zh", fingerprint=None,
        )


def test_business_retry_does_not_multiply_client_attempts(monkeypatch):
    create = Mock(side_effect=httpx.ReadTimeout("timeout"))
    client = object.__new__(TextClient)
    client.api_format = "openai"
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    client.messages = _MessagesFacade(client)
    monkeypatch.setattr(ai_client.time, "sleep", lambda _: None)
    with pytest.raises(httpx.ReadTimeout):
        ai_client._retry(client.messages.create, model="model", max_tokens=10,
                         messages=[{"role": "user", "content": "hello"}])
    assert create.call_count == 3


@pytest.mark.parametrize("api_format", ["openai", "anthropic"])
def test_sdk_has_explicit_timeout_and_no_hidden_retries(api_format):
    client = TextClient(api_format, "test-key", "https://example.com")
    try:
        assert client._client.max_retries == 0
        assert client._client.timeout.read == AI_REQUEST_TIMEOUT
        assert client._client.timeout.connect == 10
    finally:
        client._client.close()


def test_mindmap_timeout_is_not_retried(monkeypatch):
    create = Mock(side_effect=TimeoutError("timeout"))
    monkeypatch.setattr(ai_client, "_get_client", lambda: SimpleNamespace(messages=SimpleNamespace(create=create)))
    with pytest.raises(TimeoutError):
        ai_client.generate_mindmap("short transcript", "title")
    assert create.call_count == 1


def test_sse_heartbeat_and_error_terminate(monkeypatch):
    monkeypatch.setattr(stream_routes, "SSE_HEARTBEAT_SECONDS", 0.01)

    def pipeline():
        time.sleep(0.04)
        yield PipelineEvent("progress", {"stage": "mindmap_generating"})
        raise TimeoutError("mindmap timeout")

    async def consume():
        return [chunk async for chunk in stream_routes._sse_generator(pipeline())]

    chunks = asyncio.run(consume())
    assert b": heartbeat\n\n" in chunks
    assert b'"stage": "mindmap_generating"' in b''.join(chunks)
    assert b'"type": "error"' in chunks[-1]
