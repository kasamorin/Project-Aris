"""文字对话会话（aris chat）。

维护多轮对话历史（内存），流式调用 LLM，并把每轮问答作为日志落盘到
`<data_dir>/logs/YYYY-MM-DD/chat.log`，便于日后回溯与记忆系统接入。
"""

from __future__ import annotations

import datetime
import os
import select
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

from ..core.llm import ChatRequest, LLMEngine, Message
from .commands import COMMAND_HELP, PROMPT_ARIS, PROMPT_USER, parse_command

# 简单 Aris 人设（persona 模块已搁置，此处仅作为对话 CLI 的默认系统提示词）
ARIS_SYSTEM_PROMPT = (
    "你是 Aris，一个拟人 AI。"
    "你说话简洁、自然、略带温度，像一个人类朋友，不用『作为AI』之类的套话。"
    "基于对话历史自然地继续交谈。"
)

# 单个对话日志文件大小上限（超出后新建 chat.log.1、chat.log.2 ...）
_CHAT_LOG_ROTATION = 10 * 1024 * 1024


def _chat_log_path(log_dir: Path) -> Path:
    """取当日对话日志路径；文件超限时依次切新文件（.1 .2 ...）。"""
    base = log_dir / "chat.log"
    if base.exists() and base.stat().st_size >= _CHAT_LOG_ROTATION:
        index = 1
        while True:
            candidate = log_dir / f"chat.log.{index}"
            if not candidate.exists() or candidate.stat().st_size < _CHAT_LOG_ROTATION:
                return candidate
            index += 1
    return base


def _discard_pending_input() -> None:
    """丢弃终端里尚未被读取的已输入字符（typeahead）。

    Aris 流式回复期间用户可能提前输入了文字，这些字符会滞留在输入缓冲，
    若不清空会被当作下一轮的用户输入。仅对终端 stdin 有效。
    """
    if not sys.stdin.isatty():
        return
    while select.select([sys.stdin], [], [], 0)[0]:
        try:
            os.read(sys.stdin.fileno(), 65536)
        except (BlockingIOError, OSError):
            break


class ChatSession:
    """一段多轮对话：内存保存历史，流式收发消息，对话内容落盘日志。

    每次 ask() 会把用户消息与 Aris 回复追加进内存历史，并把该轮问答
    写入当日对话日志文件。
    """

    def __init__(
        self,
        engine: LLMEngine,
        *,
        model_id: str,
        system_prompt: str = ARIS_SYSTEM_PROMPT,
        data_dir: Path = Path("data"),
    ) -> None:
        self.engine = engine
        self.model_id = model_id
        self.history: list[Message] = [Message(role="system", content=system_prompt)]
        log_dir = data_dir / "logs" / datetime.date.today().isoformat()
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log_dir = log_dir

    def ask(
        self, text: str, should_stop: Callable[[], bool] | None = None
    ) -> Iterator[str]:
        """发送一条用户消息，流式返回 Aris 回复。

        回复完成后把该轮问答写入对话日志。若 should_stop 回调返回 True，
        则中断本次回复并回滚未完成的 user 消息（不写入日志）。
        """
        self.history.append(Message(role="user", content=text))
        deltas: list[str] = []
        interrupted = False
        for delta in self.engine.stream(
            ChatRequest(model_id=self.model_id, messages=list(self.history))
        ):
            if should_stop is not None and should_stop():
                interrupted = True
                break
            deltas.append(delta)
            yield delta
        if interrupted:
            if self.history and self.history[-1].role == "user":
                self.history.pop()  # 撤掉未完成轮次的用户消息
            return
        reply = "".join(deltas)
        self.history.append(Message(role="assistant", content=reply))
        self._append_log(text, reply)

    def _append_log(self, user_text: str, reply: str) -> None:
        """把一轮问答按人类可读格式追加到当日对话日志。"""
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        with _chat_log_path(self._log_dir).open("a", encoding="utf-8") as f:
            f.write(f"[{ts}] 用户: {user_text}\n")
            f.write(f"[{ts}] Aris: {reply}\n")

    def repl(self) -> int:
        """进入交互式对话循环。

        终端环境走全屏 TUI（输出区在上、输入框在底部、ESC 两次中断、
        Ctrl-C 退出）；非终端（管道/重定向）回退简单 input() 循环。
        """
        if sys.stdin.isatty():
            from .tui import ChatTUI

            return ChatTUI(self).run()

        # 非终端回退：逐行问答，Ctrl-C 中断本次回复
        print("开始与 Aris 对话（输入 /help 查看可用指令，/quit 退出）")
        while True:
            _discard_pending_input()  # 清掉上一轮回复期间残留的输入
            try:
                user_text = input(PROMPT_USER).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not user_text:
                continue
            if user_text in {"/quit", "/exit"}:
                break
            help_text = parse_command(user_text)
            if help_text:
                print(help_text)
                continue
            print(PROMPT_ARIS, end="", flush=True)
            for delta in self.ask(user_text):
                print(delta, end="", flush=True)
            print()
        return 0
