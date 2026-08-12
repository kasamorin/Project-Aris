"""请求格式化工具：把统一请求模板翻译成各提供方的请求体。

当前仅实现 chat 格式（OpenAI Chat Completions 兼容）。
后续新增 responses / anthropic 等格式时，在这里加对应函数，
transport 层按 request.format 分发。

归一化边界：内部 Message / ToolCall 是唯一真相，
所有协议差异（arguments 是 JSON 字符串、tool_calls 结构、reasoning_content 回传）
都在这里消化。
"""

from __future__ import annotations

import json

from .message import ChatRequest, Message, MessageRole

# DeepSeek 系关闭思考模式的请求体（带 tools 时默认开启思考，导致首字延迟）
_THINKING_DISABLED_BODY = {"type": "disabled"}


def _message_to_openai(msg: Message) -> dict:
    """把一条内部消息翻译成 OpenAI chat 格式。"""
    body: dict = {"role": msg.role, "content": msg.content}
    if msg.role == MessageRole.ASSISTANT:
        # DeepSeek：带 tools 时必须完整回传思考链，否则 400
        if msg.reasoning_content:
            body["reasoning_content"] = msg.reasoning_content
        if msg.tool_calls:
            body["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in msg.tool_calls
            ]
    elif msg.role == MessageRole.TOOL:
        body["tool_call_id"] = msg.tool_call_id
    return body


def to_openai_chat_body(request: ChatRequest, request_name: str) -> dict:
    """把统一请求转成 OpenAI Chat Completions 请求体。

    参数:
        request: 统一请求模板。
        request_name: 该提供方下实际请求用的模型名。
    """
    body: dict = {
        "model": request_name,
        "messages": [_message_to_openai(m) for m in request.messages],
        "stream": request.stream,
    }
    if request.temperature is not None:
        body["temperature"] = request.temperature
    if request.max_tokens is not None:
        body["max_tokens"] = request.max_tokens
    if request.tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ]
    if request.tool_choice is not None:
        body["tool_choice"] = request.tool_choice
    if request.thinking is False:
        # DeepSeek 系：显式关闭思考模式（默认开启导致首字延迟）
        body["thinking"] = _THINKING_DISABLED_BODY
    return body
