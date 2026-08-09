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

from aris.core.llm.engine import LLMEngine
from aris.core.llm.message import ChatRequest, Message

from .registry import ToolRegistry

# 流式文本增量事件回调（TUI / 非 TTY 都通过它把内容推给界面）
OnDelta = Callable[[str], None]
# 工具执行事件回调（name + 结果文本），可选，用于界面展示
OnTool = Callable[[str, str], None]
# 中断判断回调：返回 True 则中止本轮
ShouldStop = Callable[[], bool]


@dataclass
class LoopEvent:
    """agent loop 的产出事件，供上层（session）驱动流式。"""

    type: str          # delta（文本增量）/ tool（工具已执行）/ done / interrupted
    content: str = ""
    name: str = ""
    result: str = ""


class AgentLoop:
    """工具循环执行器：一次 run 跑完「LLM ↔ 工具」的完整循环。"""

    def __init__(
        self,
        engine: LLMEngine,
        *,
        registry: ToolRegistry,
        model_id: str,
        max_rounds: int = 8,
    ) -> None:
        self.engine = engine
        self.registry = registry
        self.model_id = model_id
        self.max_rounds = max_rounds

    def iter_events(
        self,
        messages: list[Message],
        *,
        thinking: bool | None = None,
        should_stop: ShouldStop | None = None,
    ) -> Iterator[LoopEvent]:
        """迭代执行循环，产出事件流（流式文本 / 工具通知 / 结束标记）。

        以 interrupted 事件结束时表示被中断（调用方应回滚未完成的 user 消息）。
        """
        work = list(messages)
        tools = self.registry.definitions()
        for _ in range(self.max_rounds):
            request = ChatRequest(
                model_id=self.model_id,
                messages=work,
                tools=tools,
                thinking=thinking,
            )
            content = ""
            reasoning = ""
            tool_calls: list = []
            finish_reason: str | None = None
            for delta in self.engine.stream_deltas(request):
                if should_stop is not None and should_stop():
                    yield LoopEvent(type="interrupted")
                    return
                if delta.content:
                    content += delta.content
                    yield LoopEvent(type="delta", content=delta.content)
                if delta.reasoning:
                    reasoning += delta.reasoning
                if delta.finish_reason:
                    finish_reason = delta.finish_reason
                    tool_calls = delta.tool_calls or []

            if finish_reason != "tool_calls":
                # 最终回答（或没有工具调用）
                yield LoopEvent(type="done", content=content)
                return

            # 执行工具并回填
            work.append(
                Message(
                    role="assistant",
                    content=content or None,
                    reasoning_content=reasoning or None,
                    tool_calls=tool_calls,
                )
            )
            for tc in tool_calls:
                result = self.registry.execute(tc.name, tc.arguments)
                yield LoopEvent(type="tool", name=tc.name, result=result)
                work.append(
                    Message(role="tool", content=result, tool_call_id=tc.id)
                )

        # 达到轮数上限：返回最后一次输出（不视为中断）
        yield LoopEvent(type="done", content=content)
