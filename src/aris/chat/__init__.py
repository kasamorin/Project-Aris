"""chat 模块 —— 文字对话。

对外暴露：
- ChatSession：多轮对话会话（内存历史 + 流式 + 对话日志落盘）
- ChatTUI：全屏终端交互界面（TUI）
- ARIS_SYSTEM_PROMPT：Aris 人设（转引自 persona 模块）
- 指令相关：COMMAND_HELP、parse_command
"""

from .session import ChatSession
from .tui import ChatTUI
from .commands import COMMAND_HELP, parse_command
from ..persona import ARIS_SYSTEM_PROMPT

__all__ = [
    "ARIS_SYSTEM_PROMPT",
    "ChatSession",
    "ChatTUI",
    "COMMAND_HELP",
    "parse_command",
]
