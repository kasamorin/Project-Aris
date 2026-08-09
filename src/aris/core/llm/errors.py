"""LLM 错误分类与处理。

把底层异常（SDK / httpx / 超时）归一化成统一的 LLMError 层级，
供 fallback 逻辑判断「是否切下家」、错误处理逻辑决定「怎么提示」。
"""

from __future__ import annotations

from typing import Any


class LLMError(Exception):
    """LLM 调用统一错误基类。"""

    def __init__(self, message: str, *, provider_id: str = "", detail: Any = None):
        super().__init__(message)
        self.provider_id = provider_id
        self.detail = detail


class LLMTimeoutError(LLMError):
    """请求超时（含总体超时预算耗尽）。"""


class AuthError(LLMError):
    """鉴权失败（401 / key 缺失）。"""


class RateLimitError(LLMError):
    """限流（429）。"""


class QuotaError(LLMError):
    """额度不足（403）。"""


class ServerError(LLMError):
    """提供方服务端错误（5xx）。"""


class NetworkError(LLMError):
    """网络层错误（连接失败、DNS 等）。"""


class NoCandidateError(LLMError):
    """没有提供方支持请求的模型。"""


_RETRYABLE = (RateLimitError, ServerError, NetworkError, LLMTimeoutError)
"""可切换下家的错误类型。AuthError / QuotaError 属于配置问题，
切下家通常也没用，但仍走 fallback 尝试顺序。"""


def is_retryable(error: LLMError) -> bool:
    """该错误是否值得切换下家重试。"""
    return isinstance(error, _RETRYABLE)


def classify_http_status(status: int, provider_id: str = "", detail: Any = None) -> LLMError:
    """按 HTTP 状态码归类错误。"""
    if status == 401:
        return AuthError(f"鉴权失败 (HTTP {status})，请检查 API key", provider_id=provider_id, detail=detail)
    if status == 429:
        return RateLimitError(f"请求受限 (HTTP {status})", provider_id=provider_id, detail=detail)
    if status == 403:
        return QuotaError(f"额度或权限不足 (HTTP {status})", provider_id=provider_id, detail=detail)
    if status >= 500:
        return ServerError(f"提供方服务端错误 (HTTP {status})", provider_id=provider_id, detail=detail)
    return LLMError(f"请求失败 (HTTP {status})", provider_id=provider_id, detail=detail)
