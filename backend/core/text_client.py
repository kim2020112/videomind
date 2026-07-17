"""Protocol-neutral text generation client for OpenAI-compatible and Anthropic APIs."""

from __future__ import annotations

import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Iterator
from urllib.parse import urlsplit, urlunsplit

import httpx

_COMPATIBLE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36 VideoMind/1.0"
)


@dataclass(frozen=True)
class DiscoveredModel:
    model: str
    name: str


@dataclass(frozen=True)
class ModelDiscoveryResult:
    models: list[DiscoveredModel]
    url: str


def _join_url(base_url: str, suffix: str) -> str:
    return f"{base_url.rstrip('/')}/{suffix.lstrip('/')}"


def model_list_candidates(api_format: str, base_url: str, override_url: str = "") -> list[tuple[str, str]]:
    """Return (url, auth style) candidates without changing the generation URL."""
    if override_url.strip():
        return [(override_url.strip().rstrip("/"), "openai")]

    parsed = urlsplit(base_url)
    path = parsed.path.rstrip("/")
    candidates: list[tuple[str, str]] = []
    if api_format == "openai":
        candidates.append((_join_url(base_url, "models"), "openai"))
    else:
        candidates.append((_join_url(base_url, "v1/models"), "anthropic"))
        sibling = path
        if sibling.endswith("/anthropic"):
            sibling = sibling[:-len("/anthropic")]
        sibling_base = urlunsplit((parsed.scheme, parsed.netloc, sibling.rstrip("/"), "", ""))
        candidates.extend([
            (_join_url(sibling_base, "models"), "openai"),
            (_join_url(sibling_base, "v1/models"), "openai"),
        ])

    unique = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def discover_model_list(api_format: str, api_key: str, base_url: str,
                        override_url: str = "", preferred_url: str = "") -> ModelDiscoveryResult:
    candidates = model_list_candidates(api_format, base_url, override_url)
    if preferred_url and not override_url:
        preferred = next((item for item in candidates if item[0] == preferred_url), None)
        if preferred:
            candidates = [preferred, *[item for item in candidates if item != preferred]]

    unsupported = []
    with httpx.Client(timeout=20) as client:
        for url, auth_style in candidates:
            headers = {"Accept": "application/json", "User-Agent": _COMPATIBLE_USER_AGENT}
            if auth_style == "anthropic":
                headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01"})
            else:
                headers["Authorization"] = f"Bearer {api_key}"
            try:
                response = retry(client.get, url, headers=headers)
            except Exception as error:
                raise ValueError(f"获取模型失败：{str(error)[:160]}") from error
            if response.status_code in {404, 405}:
                unsupported.append(response.status_code)
                continue
            if response.status_code in {401, 403}:
                raise ValueError("模型列表鉴权失败，请检查 API Key 或该密钥的模型读取权限")
            if response.status_code == 429:
                raise ValueError("模型列表请求过于频繁，请稍后重试")
            if response.status_code >= 400:
                raise ValueError(f"模型列表请求失败（HTTP {response.status_code}）")
            try:
                payload = response.json()
            except ValueError as error:
                raise ValueError("模型列表接口未返回有效 JSON") from error
            items = payload.get("data", payload.get("models", payload if isinstance(payload, list) else []))
            models = []
            for item in items if isinstance(items, list) else []:
                model_id = item.get("id") if isinstance(item, dict) else getattr(item, "id", None)
                if model_id:
                    name = item.get("display_name") or item.get("name") if isinstance(item, dict) else None
                    models.append(DiscoveredModel(str(model_id), str(name or model_id)))
            if not models:
                raise ValueError("模型列表为空，可手动添加模型")
            return ModelDiscoveryResult(sorted(models, key=lambda item: item.model.lower()), url)
    if unsupported:
        raise ValueError("生成接口可用，但中转站未提供兼容的模型列表；可手动添加模型或在高级设置中填写模型列表 URL")
    raise ValueError("无法获取模型列表")


def is_recoverable(error: Exception) -> bool:
    """Retry connection, timeout, rate-limit and server failures only."""
    status = getattr(error, "status_code", None)
    if status is not None:
        return status == 429 or status >= 500
    names = {cls.__name__ for cls in type(error).__mro__}
    if names & {"APIConnectionError", "APITimeoutError", "ConnectError", "ReadTimeout"}:
        return True
    return isinstance(error, (ConnectionError, TimeoutError, OSError))


def retry(call, *args, attempts: int = 3, base_delay: float = 2, **kwargs):
    last_error = None
    for attempt in range(attempts):
        try:
            return call(*args, **kwargs)
        except Exception as error:
            last_error = error
            if not is_recoverable(error) or attempt == attempts - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))
    raise last_error


class TextClient:
    def __init__(self, api_format: str, api_key: str, base_url: str):
        if api_format not in {"openai", "anthropic"}:
            raise ValueError("兼容格式必须是 openai 或 anthropic")
        self.api_format = api_format
        self.api_key = api_key
        self.base_url = base_url
        if api_format == "openai":
            from openai import OpenAI
            # Some OpenAI-compatible gateways block SDK user agents at their WAF layer.
            self._client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                default_headers={"User-Agent": _COMPATIBLE_USER_AGENT},
            )
        else:
            import anthropic
            # Anthropic SDK appends /v1/messages itself.
            self._client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
        self.messages = _MessagesFacade(self)

    def generate(self, model: str, prompt: str, max_tokens: int, temperature: float | None = None) -> str:
        if self.api_format == "openai":
            kwargs = {"model": model, "max_tokens": max_tokens,
                      "messages": [{"role": "user", "content": prompt}]}
            if temperature is not None:
                kwargs["temperature"] = temperature
            response = retry(self._client.chat.completions.create, **kwargs)
            text = response.choices[0].message.content if response.choices else ""
        else:
            kwargs = {"model": model, "max_tokens": max_tokens,
                      "messages": [{"role": "user", "content": prompt}]}
            if temperature is not None:
                kwargs["temperature"] = temperature
            response = retry(self._client.messages.create, **kwargs)
            text = next((block.text for block in response.content if hasattr(block, "text")), "")
        if not text or not text.strip():
            raise ValueError("API 响应中未找到文本内容")
        return text.strip()

    def stream(self, model: str, prompt: str, max_tokens: int) -> Iterator[str]:
        if self.api_format == "openai":
            response = self._client.chat.completions.create(
                model=model, max_tokens=max_tokens, stream=True,
                messages=[{"role": "user", "content": prompt}],
            )
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
            return
        with self._client.messages.stream(
            model=model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                if text:
                    yield text

    def list_models(self, override_url: str = "", preferred_url: str = "") -> ModelDiscoveryResult:
        return discover_model_list(self.api_format, self.api_key, self.base_url, override_url, preferred_url)

    def test_model(self, model: str) -> dict:
        text = self.generate(model, "请只回复 OK", 8)
        normalized = text.strip().rstrip(".!。！").strip().upper()
        if normalized != "OK":
            raise ValueError(f"模型未按预期响应：{text[:120]}")
        return {"success": True, "message": "模型可用：OK", "model": model}


class _StreamFacade:
    def __init__(self, chunks):
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __iter__(self):
        for text in self._chunks:
            yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(text=text))


class _MessagesFacade:
    """Temporary Anthropic-shaped boundary for existing business functions."""
    def __init__(self, client: TextClient):
        self._client = client

    def create(self, *, model, max_tokens, messages, temperature=None):
        text = self._client.generate(model, messages[-1]["content"], max_tokens, temperature)
        return SimpleNamespace(content=[SimpleNamespace(text=text)])

    def stream(self, *, model, max_tokens, messages):
        return _StreamFacade(self._client.stream(model, messages[-1]["content"], max_tokens))
