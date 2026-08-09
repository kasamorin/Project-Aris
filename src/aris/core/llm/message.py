"""统一消息模板。

所有 LLM 请求都用这套内部消息结构表达，不直接依赖具体提供方的字段格式。
格式化工具（formatters.py）负责把内部消息翻译成各提供方（chat / responses 等）的请求体。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Message:
    """一条统一消息。

    只覆盖当前需要的角色（system / user / assistant）。
    后续引入工具调用时再扩展 tool_calls、tool_call_id 等字段。
    """

    role: str
    content: str


@dataclass
class ChatRequest:
    """统一请求模板。

    format 标记请求格式（当前仅 "chat"），格式化工具据此选择翻译方案。
    model_id 是统一模型 id（跨提供方共享），由 fallback 逻辑解析到具体提供方的请求名。
    """

    model_id: str
    messages: list[Message]
    format: str = "chat"
    stream: bool = True
    temperature: float | None = None
    max_tokens: int | None = None


def plain_chat(model_id: str, text: str, system: str | None = None) -> ChatRequest:
    """便捷构造：单轮纯文本对话请求。"""
    messages: list[Message] = []
    if system:
        messages.append(Message(role="system", content=system))
    messages.append(Message(role="user", content=text))
    return ChatRequest(model_id=model_id, messages=messages)
