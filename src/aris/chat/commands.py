"""对话指令：解析与帮助文本。

所有以 / 开头的对话指令集中在这里定义，TUI 与非 TUI 回退共用。
"""

from __future__ import annotations

# 指令名 -> 说明（按展示顺序）
COMMANDS: dict[str, str] = {
    "/help": "查看可用指令",
    "/quit": "退出对话（同 /exit）",
    "/exit": "退出对话（同 /quit）",
}

# 提示符（与 TUI / 回退模式一致）
PROMPT_USER = "你> "
PROMPT_ARIS = "Aris: "

COMMAND_HELP = "可用指令：\n" + "\n".join(
    f"  {name:<10} {desc}" for name, desc in COMMANDS.items()
) + "\n双击 ESC 可中断 Aris 的回复，Ctrl-C 退出程序。"


def parse_command(text: str) -> str | None:
    """解析以 / 开头的指令。

    返回指令对应的响应文本（将展示给用户），若输入不是指令返回 None。
    /quit /exit 返回 None，由调用方处理退出。
    """
    cmd = text.strip().lower()
    if cmd in {"/quit", "/exit"}:
        return None
    if cmd == "/help":
        return COMMAND_HELP
    return None
