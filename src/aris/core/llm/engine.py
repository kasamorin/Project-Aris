"""LLM 调用编排：fallback + 超时预算 + 错误处理。

流程：
1. 按请求的模型 id 从配置里挑出候选提供方（按 default_provider_order 排序）。
2. 逐个尝试：报错就切下家；总体超时预算 N 秒（含切换耗时）耗尽则停止。
3. 全部失败或超时 → 错误处理逻辑：记录日志、广播提醒（弹窗/推送）、
   返回预设提示语（不把原始报错暴露给用户界面）。
"""

from __future__ import annotations

import time
from collections.abc import Iterator

from loguru import logger

from ..bus import provide
from .config import ProviderConfig
from .errors import LLMError, NoCandidateError, is_retryable
from .message import ChatRequest
from .transport import StreamDelta, stream_chat


class LLMEngine:
    """LLM 统一出入口：负责多提供方 fallback 与错误处理。"""

    def __init__(self, providers: ProviderConfig, *, timeout: float, error_message: str):
        self.providers = providers
        self.timeout = timeout  # 总体超时预算（秒）
        self.error_message = error_message
        # 注册为统一服务（实例自注册，重名覆盖会记警告）
        provide("llm.stream", self.stream)        # 纯文本流式（简单场景）
        provide("llm.deltas", self.stream_deltas)  # 完整增量流式（agent loop 用）

    def stream(self, request: ChatRequest) -> Iterator[str]:
        """纯文本流式：过滤掉完成事件，只产出文本增量。

        适合单次问答、简单场景；需要工具调用信息时用 stream_deltas()。
        """
        for d in self._stream_deltas(request):
            if d.content:
                yield d.content

    def stream_deltas(self, request: ChatRequest) -> Iterator[StreamDelta]:
        """完整流式增量（含流结束的完成事件）。

        完成事件（finish_reason 非 None）携带本轮拼好的完整 tool_calls，
        供 behavior 的 agent loop 判断是否要执行工具并继续。
        """
        yield from self._stream_deltas(request)

    def _stream_deltas(self, request: ChatRequest) -> Iterator[StreamDelta]:
        candidates = self.providers.candidates_for(request.model_id)
        if not candidates:
            yield from self._handle_failure(
                NoCandidateError(
                    f"没有任何提供方支持模型 {request.model_id}，请在 providers.toml 配置",
                    detail=request.model_id,
                )
            )
            return

        start = time.monotonic()
        for provider in candidates:
            remaining = self.timeout - (time.monotonic() - start)
            if remaining <= 0:
                logger.warning("总体超时预算已耗尽，停止切换下家")
                break
            attempt_timeout = min(provider.timeout, remaining)
            logger.info(f"尝试提供方 {provider.id}（模型 {request.model_id}）")
            try:
                emitted = False
                for delta in stream_chat(provider, request, timeout=attempt_timeout):
                    # 透传文本增量 + 完成事件（content 为空但 finish_reason 有值）
                    if delta.content or delta.reasoning or delta.finish_reason:
                        emitted = True
                        yield delta
                return  # 该提供方完整成功，结束
            except LLMError as e:
                e.provider_id = provider.id
                logger.error(f"提供方 {provider.id} 失败: {e}")
                if emitted:
                    # 已输出过内容才中断：不宜再切换，直接进错误处理
                    logger.error(f"提供方 {provider.id} 中途失败，已输出部分内容，进入错误处理")
                    yield from self._handle_failure(e)
                    return
                continue  # 未输出任何内容，切换下家

        logger.error("所有候选提供方均失败或超时，进入错误处理")
        yield from self._handle_failure(LLMError("所有提供方均失败"))

    def _handle_failure(self, error: LLMError) -> Iterator[StreamDelta]:
        """错误处理逻辑：记录日志、广播提醒、返回预设提示语。"""
        logger.error(f"LLM 调用失败（{error.__class__.__name__}）: {error}")
        from .notify import broadcast

        broadcast(
            "Aris LLM 连接异常",
            f"所有提供方均失败：{error}",
        )
        yield StreamDelta(content=self.error_message)
