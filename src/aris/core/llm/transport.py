"""请求执行工具：把格式化好的请求体发给提供方并消费响应。

两种传输实现：
- sdk：openai 官方 SDK（默认，成熟省事，base_url 指向任意兼容端点）
- httpx：手写 HTTP 请求（零 SDK 依赖，便于调试与兜底）

两者都产出统一的流式增量事件 StreamDelta，供上层消费。
当前只支持 chat 格式；后续新增格式在对应函数里扩展。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Iterator

import httpx
from loguru import logger

from .config import LLMProvider
from .errors import (
    AuthError,
    LLMError,
    LLMTimeoutError,
    NetworkError,
    classify_http_status,
)
from .formatters import to_openai_chat_body
from .message import ChatRequest


@dataclass
class StreamDelta:
    """一次流式增量（文本 / 思考链）。"""

    content: str = ""
    reasoning: str = ""


def stream_chat(provider: LLMProvider, request: ChatRequest, timeout: float) -> Iterator[StreamDelta]:
    """按提供方配置的传输方式流式请求 chat 格式。"""
    if provider.transport == "httpx":
        yield from _stream_httpx(provider, request, timeout)
    else:
        yield from _stream_openai_sdk(provider, request, timeout)


def _api_key(provider: LLMProvider) -> str:
    """从环境变量读取该提供方的 API key。

    若当前进程未注入（如被直接 import 使用而非走 CLI 入口），
    先尝试把 .env 同步进 os.environ 再读取。
    """
    from aris.config import _load_env_into_environ

    _load_env_into_environ()
    key = os.environ.get(provider.api_key_env)
    if not key:
        raise AuthError(
            f"未找到 API key，请在 .env 设置 {provider.api_key_env}",
            provider_id=provider.id,
        )
    return key


def _stream_openai_sdk(provider: LLMProvider, request: ChatRequest, timeout: float) -> Iterator[StreamDelta]:
    """openai SDK 实现。"""
    try:
        from openai import OpenAI
    except ImportError as e:
        raise LLMError(f"openai SDK 未安装: {e}", provider_id=provider.id) from e

    model = provider.get_model(request.model_id)
    if model is None:
        raise LLMError(f"提供方 {provider.id} 不支持模型 {request.model_id}", provider_id=provider.id)

    client = OpenAI(api_key=_api_key(provider), base_url=provider.base_url, timeout=timeout)
    body = to_openai_chat_body(request, model.request_name)

    try:
        stream = client.chat.completions.create(**body)
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            content = delta.content or ""
            reasoning = getattr(delta, "reasoning_content", None) or ""
            if content or reasoning:
                yield StreamDelta(content=content, reasoning=reasoning)
    except Exception as e:
        raise _wrap_sdk_error(e, provider.id)


def _stream_httpx(provider: LLMProvider, request: ChatRequest, timeout: float) -> Iterator[StreamDelta]:
    """httpx 手写实现（SSE 解析）。"""
    model = provider.get_model(request.model_id)
    if model is None:
        raise LLMError(f"提供方 {provider.id} 不支持模型 {request.model_id}", provider_id=provider.id)

    url = f"{provider.base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {_api_key(provider)}",
        "Content-Type": "application/json",
    }
    body = to_openai_chat_body(request, model.request_name)

    try:
        with httpx.stream("POST", url, json=body, headers=headers, timeout=timeout) as resp:
            if resp.status_code >= 400:
                detail = resp.read().decode("utf-8", errors="replace")
                raise classify_http_status(resp.status_code, provider.id, detail)
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    logger.debug(f"忽略无法解析的 SSE 行: {line}")
                    continue
                if not obj.get("choices"):
                    continue
                delta = obj["choices"][0].get("delta", {}) or {}
                content = delta.get("content") or ""
                reasoning = delta.get("reasoning_content") or ""
                if content or reasoning:
                    yield StreamDelta(content=content, reasoning=reasoning)
    except LLMError:
        raise
    except httpx.TimeoutException as e:
        raise LLMTimeoutError(f"请求超时 ({timeout}s)", provider_id=provider.id) from e
    except httpx.HTTPError as e:
        raise NetworkError(f"网络错误: {e}", provider_id=provider.id) from e


def _wrap_sdk_error(e: Exception, provider_id: str) -> LLMError:
    """把 openai SDK 异常归一化成 LLMError 层级。"""
    from openai import AuthenticationError as SdkAuthError
    from openai import RateLimitError as SdkRateLimitError
    from openai import APIStatusError, APITimeoutError

    if isinstance(e, APITimeoutError):
        return LLMTimeoutError(f"请求超时: {e}", provider_id=provider_id)
    if isinstance(e, SdkAuthError):
        return AuthError(f"鉴权失败: {e}", provider_id=provider_id)
    if isinstance(e, SdkRateLimitError):
        return RateLimitError(f"请求受限: {e}", provider_id=provider_id)
    if isinstance(e, APIStatusError):
        return classify_http_status(e.status_code, provider_id, str(e))
    return LLMError(f"SDK 调用失败: {e}", provider_id=provider_id)
