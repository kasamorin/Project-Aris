"""behavior 模块 —— 行为编排。

对外暴露：
- ToolRegistry：工具注册表（工具统一注册/执行入口）
- AgentLoop：agent loop（LLM ↔ 工具执行循环）
- BrowserManager：浏览器管理器（联网搜索用，会话内常驻）
- register_builtin_tools：注册全部内置工具
"""

from .browser import BrowserManager
from .loop import AgentLoop, LoopEvent
from .registry import RegisteredTool, ToolRegistry
from .tools import register_builtin_tools

__all__ = [
    "AgentLoop",
    "LoopEvent",
    "BrowserManager",
    "RegisteredTool",
    "ToolRegistry",
    "register_builtin_tools",
]
