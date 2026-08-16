"""agent loop：LLM 与工具之间的执行循环。

流程（每轮）：
1. 用当前消息列表 + 工具定义发请求，流式收文本（作为事件透传）。
2. 流结束看完成事件（finish_reason）：
   - 非 tool_calls：本轮是最终回答，结束。
   - tool_calls：把工具调用与结果作为 tool 消息回填，进入下一轮。
最多 max_rounds 轮防死循环。

中间轮（tool_calls + tool 结果）只在循环内存在，不修改传入的消息列表——
持久历史（ChatSession.history）只收最终回答，工具细节不污染。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import StrEnum

from aris.cfgtoml import load_config
from aris.core.bus import call, provide
from aris.core.llm.engine import LLMEngine
from aris.core.llm.message import ChatRequest, FinishReason, Message, MessageRole

from .registry import ToolRegistry

# 流式文本增量事件回调（TUI / 非 TTY 都通过它把内容推给界面）
OnDelta = Callable[[str], None]
# 工具执行事件回调（name + 结果文本），可选，用于界面展示
OnTool = Callable[[str, str], None]
# 中断判断回调：返回 True 则中止本轮
ShouldStop = Callable[[], bool]


class LoopEventType(StrEnum):
    """agent loop 产出事件类型。"""

    DELTA = "delta"            # 流式文本增量
    TOOL = "tool"              # 工具已执行（附 name + result）
    DONE = "done"              # 最终回答结束
    STALL = "stall"            # 首字占位提示（超时无产出；不并入最终回答）
    INTERRUPTED = "interrupted"  # 用户中断（调用方应回滚未完成 user 消息）


@dataclass
class LoopConfig:
    """agent loop 可调参数（config/chat.toml）。"""

    max_rounds: int = 8


_loop_config = load_config(LoopConfig(), "chat.toml")


@dataclass
class LoopEvent:
    """agent loop 的产出事件，供上层（session）驱动流式。

    model_id / degraded / race_possible 仅 DONE 事件携带：
    - model_id：本轮实际生效的模型（竞速/降级后可能不同于会话当前模型）
    - degraded：本轮是否经过降级（竞速输给备选 / 模型级降级）
    - race_possible：是否可参与下次「本家 vs 备选」竞速恢复
    """

    type: str          # LoopEventType
    content: str = ""
    name: str = ""
    result: str = ""
    model_id: str = ""
    degraded: bool = False
    race_possible: bool = False


class AgentLoop:
    """工具循环执行器：一次 run 跑完「LLM ↔ 工具」的完整循环。"""

    def __init__(
        self,
        engine: LLMEngine,
        *,
        registry: ToolRegistry,
        model_id: str,
        max_rounds: int | None = None,
    ) -> None:
        self.engine = engine
        self.registry = registry
        self.model_id = model_id
        self.max_rounds = _loop_config.max_rounds if max_rounds is None else max_rounds
        # 注册为统一服务：agent loop 统一走 core.call("loop.run", ...)
        provide("loop.run", self.iter_events)
        provide("loop.set_model", self.set_model)

    def set_model(self, model_id: str) -> None:
        """切换模型：仅更新内部 model id，后续请求使用新模型。"""
        self.model_id = model_id

    def iter_events(
        self,
        messages: list[Message],
        *,
        thinking: bool | None = None,
        should_stop: ShouldStop | None = None,
        race_model: str | None = None,
    ) -> Iterator[LoopEvent]:
        """迭代执行循环，产出事件流（流式文本 / 工具通知 / 结束标记）。

        race_model：传入降级后实际生效的模型 id 时，本轮改为「本家 vs 备选」
        并发竞速（llm.race）；DONE 携带实际生效的 model_id / degraded /
        race_possible，供上层决定下一轮是否继续竞速恢复。
        以 interrupted 事件结束时表示被中断（调用方应回滚未完成的 user 消息）。
        """
        work = list(messages)
        tools = self.registry.definitions()
        for _ in range(self.max_rounds):
            base_request = ChatRequest(
                model_id=self.model_id,
                messages=work,
                tools=tools,
                thinking=thinking,
            )
            if race_model is not None and race_model != self.model_id:
                fallback_request = ChatRequest(
                    model_id=race_model,
                    messages=work,
                    tools=tools,
                    thinking=thinking,
                )
                deltas = call("llm.race", base_request, fallback_request)
            else:
                deltas = call("llm.deltas", base_request)
            content = ""
            reasoning = ""
            tool_calls: list = []
            finish_reason: str | None = None
            model_id: str | None = None
            degraded = False
            race_possible = False
            for delta in deltas:
                if should_stop is not None and should_stop():
                    yield LoopEvent(type=LoopEventType.INTERRUPTED)
                    return
                if delta.stall:
                    yield LoopEvent(type=LoopEventType.STALL, content=delta.content)
                    continue
                if delta.content:
                    content += delta.content
                    yield LoopEvent(type=LoopEventType.DELTA, content=delta.content)
                if delta.reasoning:
                    reasoning += delta.reasoning
                if delta.finish_reason:
                    finish_reason = delta.finish_reason
                    tool_calls = delta.tool_calls or []
                    model_id = delta.model_id
                    degraded = delta.degraded
                    race_possible = delta.race_possible

            if finish_reason != FinishReason.TOOL_CALLS:
                # 最终回答（或没有工具调用）
                yield LoopEvent(
                    type=LoopEventType.DONE,
                    content=content,
                    model_id=model_id or self.model_id,
                    degraded=degraded,
                    race_possible=race_possible,
                )
                return

            # 执行工具并回填
            work.append(
                Message(
                    role=MessageRole.ASSISTANT,
                    content=content or None,
                    reasoning_content=reasoning or None,
                    tool_calls=tool_calls,
                )
            )
            for tc in tool_calls:
                # 对话文本作为 context 传入（去掉 system 提示词），供需要校验
                # 「URL 是否在对话中出现」的工具（http_request）使用
                ctx = "\n".join(
                    m.content or "" for m in work if m.role != MessageRole.SYSTEM
                )[-20000:]
                result = call("tools.execute", tc.name, tc.arguments, context=ctx)
                yield LoopEvent(type=LoopEventType.TOOL, name=tc.name, result=result)
                work.append(
                    Message(role=MessageRole.TOOL, content=result, tool_call_id=tc.id)
                )

        # 达到轮数上限：返回最后一次输出（不视为中断）
        yield LoopEvent(
            type=LoopEventType.DONE,
            content=content,
            model_id=model_id or self.model_id,
            degraded=degraded,
            race_possible=race_possible,
        )
