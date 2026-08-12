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
from dataclasses import dataclass
from pathlib import Path

from aris.cfgtoml import load_config
from ..behavior import (
    AgentLoop,
    LoopEventType,
    ToolRegistry,
    register_builtin_tools,
)
from ..core import call
from ..core.llm import ChatRequest, LLMEngine, Message, MessageRole
from .commands import (
    COMMAND_HELP,
    PROMPT_ARIS,
    PROMPT_USER,
    ParsedCommand,
    parse_command,
)

# 简单 Aris 人设（persona 模块已搁置，此处仅作为对话 CLI 的默认系统提示词）
ARIS_SYSTEM_PROMPT = (
    "你是 Aris，一个拟人 AI。"
    "你说话简洁、自然、略带温度，像一个人类朋友，不用『作为AI』之类的套话。"
    "基于对话历史自然地继续交谈。"
)

# 工具可用时追加到系统提示词
TOOLS_SYSTEM_HINT = (
    "当需要实时信息（如当前时间、资料搜索）时使用提供的工具，使用前简单说明一句。"
)


@dataclass
class ChatConfig:
    """chat 模块可调参数（config/chat.toml）。"""

    log_rotation_bytes: int = 10 * 1024 * 1024
    tool_result_preview_len: int = 60


_chat_config = load_config(ChatConfig(), "chat.toml")


@dataclass
class CommandResult:
    """指令执行结果：反馈文本 + UI 动作标记（退出 / 清屏）。"""

    text: str = ""
    quit: bool = False
    clear: bool = False


def _chat_log_path(log_dir: Path) -> Path:
    """取当日对话日志路径；文件超限时依次切新文件（.1 .2 ...）。"""
    base = log_dir / "chat.log"
    if base.exists() and base.stat().st_size >= _chat_config.log_rotation_bytes:
        index = 1
        while True:
            candidate = log_dir / f"chat.log.{index}"
            if not candidate.exists() or candidate.stat().st_size < _chat_config.log_rotation_bytes:
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
        data_dir: Path | None = None,
        thinking: bool = False,
        tools_enabled: bool = True,
        registry: ToolRegistry | None = None,
    ) -> None:
        if data_dir is None:
            from ..config import get_settings

            data_dir = get_settings().data_dir
        self.engine = engine
        self.model_id = model_id
        self._system_prompt = system_prompt
        self.available_models = engine.providers.all_model_ids()
        self.thinking = thinking  # 默认关闭思考模式（首字更快），--thinking 开启
        self.tools_enabled = tools_enabled
        self.registry = registry if registry is not None else ToolRegistry()
        if tools_enabled:
            register_builtin_tools(self.registry)
            system_prompt = f"{system_prompt} {TOOLS_SYSTEM_HINT}"
        self.history: list[Message] = [Message(role=MessageRole.SYSTEM, content=system_prompt)]
        self._loop = AgentLoop(
            engine, registry=self.registry, model_id=model_id
        )
        log_dir = data_dir / "logs" / datetime.date.today().isoformat()
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log_dir = log_dir

    def new(self) -> str:
        """清空对话历史，开启新会话（保留系统提示词），返回反馈文本。"""
        self.history = [Message(role=MessageRole.SYSTEM, content=self._system_prompt)]
        return "已开启新会话，对话历史已清空。"

    def set_model(self, model_id: str) -> str:
        """切换模型；id 不在可用列表时返回错误文本，不切换。"""
        if model_id in self.available_models:
            self.model_id = model_id
            call("loop.set_model", model_id)
            return f"已切换模型：{model_id}"
        hint = "\n".join(f"  {mid}" for mid in self.available_models)
        return f"未知模型 {model_id}，可用模型：\n{hint}"

    def close(self) -> None:
        """释放会话占用的资源。幂等，可安全多次调用。

        当前会话无外部资源（浏览器方案已移除，联网搜索走 Tavily API），
        保留方法以兼容调用方（TUI / repl 的退出路径）。
        """

    def run_command(self, parsed: ParsedCommand) -> CommandResult:
        """执行一条已解析的对话指令，返回 UI 层需要的结果。"""
        if parsed.name in {"quit", "exit"}:
            return CommandResult(text="", quit=True)
        if parsed.name == "help":
            return CommandResult(text=COMMAND_HELP)
        if parsed.name == "new":
            return CommandResult(text=self.new())
        if parsed.name == "clear":
            return CommandResult(text="", clear=True)
        if parsed.name == "model":
            if parsed.arg:
                return CommandResult(text=self.set_model(parsed.arg))
            models = "\n".join(f"  {mid}" for mid in self.available_models)
            return CommandResult(text=f"当前模型：{self.model_id}\n可用模型：\n{models}")
        return CommandResult(text=f"未知指令 /{parsed.name}，输入 /help 查看可用指令")

    def ask(
        self,
        text: str,
        should_stop: Callable[[], bool] | None = None,
        on_tool: Callable[[str, str], None] | None = None,
    ) -> Iterator[str]:
        """发送一条用户消息，流式返回 Aris 回复。

        走 agent loop（LLM ↔ 工具）：文本增量逐段 yield，工具调用与结果
        经 on_tool 回调通知。回复完成后把该轮问答写入对话日志。
        若 should_stop 回调返回 True，则中断并回滚未完成的 user 消息。
        """
        self.history.append(Message(role=MessageRole.USER, content=text))
        interrupted = False
        reply = ""
        for event in call("loop.run", list(self.history), thinking=self.thinking, should_stop=should_stop):
            if event.type == LoopEventType.DELTA:
                yield event.content
            elif event.type == LoopEventType.TOOL:
                if on_tool is not None:
                    on_tool(event.name, event.result)
            elif event.type == LoopEventType.INTERRUPTED:
                interrupted = True
                break
            elif event.type == LoopEventType.DONE:
                reply = event.content
        if interrupted:
            if self.history and self.history[-1].role == MessageRole.USER:
                self.history.pop()  # 撤掉未完成轮次的用户消息
            return
        self.history.append(Message(role=MessageRole.ASSISTANT, content=reply))
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
            parsed = parse_command(user_text)
            if parsed is not None:
                result = self.run_command(parsed)
                if result.quit:
                    break
                if result.clear:
                    print("\n" * 3)  # 非终端没有界面可清，仅刷屏分隔
                if result.text:
                    print(result.text)
                continue
            print(PROMPT_ARIS, end="", flush=True)
            for delta in self.ask(
                user_text,
                on_tool=lambda name, result: print(
                    f"\n  [调用工具 {name} → {result[:_chat_config.tool_result_preview_len]}]\n",
                    end="",
                    flush=True,
                ),
            ):
                print(delta, end="", flush=True)
            print()
        self.close()  # 释放浏览器等会话资源
        return 0
