"""请求格式化工具：把统一请求模板翻译成各提供方的请求体。

当前仅实现 chat 格式（OpenAI Chat Completions 兼容）。
后续新增 responses / anthropic 等格式时，在这里加对应函数，
transport 层按 request.format 分发。
"""

from __future__ import annotations

from .message import ChatRequest


def to_openai_chat_body(request: ChatRequest, request_name: str) -> dict:
    """把统一请求转成 OpenAI Chat Completions 请求体。

    参数:
        request: 统一请求模板。
        request_name: 该提供方下实际请求用的模型名。
    """
    body: dict = {
        "model": request_name,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        "stream": request.stream,
    }
    if request.temperature is not None:
        body["temperature"] = request.temperature
    if request.max_tokens is not None:
        body["max_tokens"] = request.max_tokens
    return body
