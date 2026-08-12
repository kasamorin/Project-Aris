"""统一消息模板。

所有 LLM 请求都用这套内部消息结构表达，不直接依赖具体提供方的字段格式。
格式化工具（formatters.py）负责把内部消息翻译成各提供方（chat / responses 等）的请求体。

工具调用归一化（对齐 API-CALL.md 第 6 节设计建议）：
- 工具定义 → ToolDefinition（{name, description, parameters}）
- 模型返回 → ToolCall（{id, name, arguments(dict)}，arguments 已归一化为 dict）
- 结果回传 → Message(role="tool")，翻译层再按提供方转 role:"tool" / tool_result
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class MessageRole(StrEnum):
    """统一消息角色（OpenAI chat 兼容）。"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ApiFormat(StrEnum):
    """请求格式（当前仅 chat；新增格式在此扩展）。"""

    CHAT = "chat"


class FinishReason(StrEnum):
    """流结束原因（协议透传；目前只判断 tool_calls）。"""

    TOOL_CALLS = "tool_calls"


@dataclass
class ToolCall:
    """模型发起的一次工具调用（内部统一形态）。

    arguments 已归一化为 dict（协议里通常是 JSON 字符串，翻译层负责解析）。
    """

    id: str
    name: str
    arguments: dict


@dataclass
class ToolDefinition:
    """一个可用工具的说明书（给 LLM 看的 schema）。

    parameters 是 JSON Schema（dict 透传，保持灵活）。
    不绑定执行函数——engine 不感知工具，执行逻辑在 behavior.registry。
    """

    name: str
    description: str
    parameters: dict


@dataclass
class Message:
    """一条统一消息。

    role: MessageRole（system / user / assistant / tool）。
    - assistant 纯工具调用轮 content 为 None（内容在 tool_calls）
    - role=TOOL 的结果消息带 tool_call_id 回填
    - reasoning_content 是思考链（DeepSeek：请求带 tools 时必须完整回传，
      否则返回 400，见 API-CALL.md 2.3 节）
    """

    role: str
    content: str | None
    reasoning_content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


@dataclass
class ChatRequest:
    """统一请求模板。

    format 标记请求格式（ApiFormat，当前仅 "chat"），格式化工具据此选择翻译方案。
    model_id 是统一模型 id（跨提供方共享），由 fallback 逻辑解析到具体提供方的请求名。
    thinking：None 不传（跟提供方默认）；False 关闭思考模式（DeepSeek 系参数）。
    """

    model_id: str
    messages: list[Message]
    format: str = ApiFormat.CHAT
    stream: bool = True
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[ToolDefinition] | None = None
    tool_choice: str | dict | None = None
    thinking: bool | None = None


def plain_chat(model_id: str, text: str, system: str | None = None) -> ChatRequest:
    """便捷构造：单轮纯文本对话请求。"""
    messages: list[Message] = []
    if system:
        messages.append(Message(role=MessageRole.SYSTEM, content=system))
    messages.append(Message(role=MessageRole.USER, content=text))
    return ChatRequest(model_id=model_id, messages=messages)
