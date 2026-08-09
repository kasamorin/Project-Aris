"""工具注册表：统一登记工具的执行函数与 schema。

所有工具（内置 / MCP / 联网搜索 / Skills）都注册到这里，
behavior 的 agent loop 通过 execute 执行调用。
执行失败宽容降级：返回错误文本给模型消化，不抛到 UI（设计哲学第 3 条）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from aris.core.llm.message import ToolDefinition

# 工具执行函数：接收关键字参数（已由模型按 schema 填好），返回任意可序列化结果
ToolFn = Callable[..., Any]


@dataclass
class RegisteredTool:
    """注册表里的一项：定义（给 LLM 看）+ 执行函数。"""

    definition: ToolDefinition
    fn: ToolFn


class ToolRegistry:
    """工具注册表：name → RegisteredTool。"""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        name: str,
        *,
        description: str,
        parameters: dict,
        fn: ToolFn,
    ) -> None:
        """注册一个工具。重名时覆盖（后注册优先）。"""
        self._tools[name] = RegisteredTool(
            definition=ToolDefinition(name=name, description=description, parameters=parameters),
            fn=fn,
        )

    def definitions(self) -> list[ToolDefinition]:
        """返回全部工具定义（按注册顺序），供请求携带。"""
        return [t.definition for t in self._tools.values()]

    def execute(self, name: str, arguments: dict) -> str:
        """执行工具，返回文本形式的结果。

        工具不存在 / 参数不匹配 / 执行抛错时，都返回人类可读的错误文本
        （宽容降级：模型会读到错误并自己决定下一步）。
        """
        tool = self._tools.get(name)
        if tool is None:
            return f"[工具 {name} 未注册，无法执行]"
        try:
            result = tool.fn(**arguments)
        except TypeError as e:
            return f"[工具 {name} 调用失败，参数不匹配: {e}]"
        except Exception as e:  # noqa: BLE001 —— 工具实现错误统一降级
            return f"[工具 {name} 执行失败: {e}]"
        return self._stringify(result)

    @staticmethod
    def _stringify(result: Any) -> str:
        """把任意结果转成文本（dict/list 序列化为 JSON）。"""
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False)
