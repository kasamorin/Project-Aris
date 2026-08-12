"""llm 子包 —— LLM 统一连接出入口。

对外暴露：
- load_providers：从 config/providers.toml 加载提供方配置
- LLMEngine：多提供方 fallback + 超时预算 + 错误处理
- ChatRequest / Message：统一请求模板
- plain_chat：便捷构造单轮对话请求
"""

from .config import (
    LLMModel,
    LLMProvider,
    ProviderConfig,
    ProviderConfigError,
    TransportKind,
    load_providers,
)
from .engine import LLMEngine
from .message import (
    ApiFormat,
    ChatRequest,
    FinishReason,
    Message,
    MessageRole,
    ToolCall,
    ToolDefinition,
    plain_chat,
)

__all__ = [
    "LLMModel",
    "LLMProvider",
    "ProviderConfig",
    "ProviderConfigError",
    "TransportKind",
    "load_providers",
    "LLMEngine",
    "ApiFormat",
    "ChatRequest",
    "FinishReason",
    "Message",
    "MessageRole",
    "ToolCall",
    "ToolDefinition",
    "plain_chat",
]
