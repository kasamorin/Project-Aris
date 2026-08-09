"""全屏 TUI 文字对话界面（aris chat 交互模式）。

布局：上方只读输出区（对话记录 + 流式回复，自动滚动），底部输入框。
交互规则：
- Enter 发送消息，Shift+Enter 换行（输入框支持多行）
- 上下方向键回看/复用历史输入（光标在首行/末行时触发）
- Aris 回复期间输入框只读（禁止输入文本），可按两次 ESC 中断回复
- 第一次按 ESC 提示「再按一次」，短时间（0.8s）内再按才真正中断
- Ctrl-C 退出程序
- 输入 /help 查看可用指令
非终端环境回退到简单 input() 循环（见 chat.session.ChatSession.repl）。
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.filters import in_paste_mode
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.key_binding.defaults import load_key_bindings
from prompt_toolkit.layout.containers import HSplit
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.widgets import TextArea

from .commands import PROMPT_ARIS, PROMPT_USER, parse_command
from .session import ChatSession

# 两次 ESC 间隔在此值（秒）内视为双击中断
# 注意：prompt_toolkit 对 ESC 有 timeoutlen 内部延迟，handler 实际间隔
# ≈ 真实按键间隔 + timeoutlen，故阈值需略宽
_ESC_DOUBLE_GAP = 0.8

# 盲文加载动画帧（等待首字到达时旋转，内容开始输出即消失）
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_SPINNER_INTERVAL = 0.1


class ToolNotice:
    """工具执行通知（后台线程入队，UI 侧渲染）。"""

    def __init__(self, *, name: str, result: str) -> None:
        self.name = name
        self.result = result


class ChatTUI:
    """基于 prompt_toolkit 的全屏对话界面。"""

    def __init__(self, session: ChatSession) -> None:
        self.session = session
        self._cancel_event = threading.Event()
        self._delta_queue: queue.Queue[str | ToolNotice | None] = queue.Queue()
        self._last_esc = 0.0
        self._generating = False

        self.output_area = TextArea(
            read_only=True,
            wrap_lines=True,
            scrollbar=True,
            focusable=False,
            height=Dimension(weight=1),
        )
        self.input_area = TextArea(
            multiline=True,
            prompt=PROMPT_USER,
            accept_handler=self._on_accept,
            history=InMemoryHistory(),
            height=Dimension(preferred=1, max=5),
        )
        self._output_text = ""
        # 盲文加载动画状态：spinner 在 _output_text 末尾旋转，首个内容 delta 到达即移除
        self._spinner_active = False
        self._spinner_pos = 0
        self._append_output("开始与 Aris 对话（输入 /help 查看指令，ESC 两次中断回复，Ctrl-C 退出）\n")

        self.app = Application(
            layout=Layout(HSplit([self.output_area, self.input_area])),
            key_bindings=merge_key_bindings(
                [load_key_bindings(), self._build_key_bindings()]
            ),
            full_screen=True,
            mouse_support=True,
        )
        # ESC 作为 meta 前缀时 prompt_toolkit 会等待 timeoutlen 确认是否独立按键，
        # 调小该值让双击 ESC 能被及时识别
        self.app.timeoutlen = 0.2
    # --- 界面渲染 ---
    def _set_output_document(self) -> None:
        """把当前 _output_text 渲染到输出区（bypass_readonly 允许写只读 buffer）。"""
        self.output_area.buffer.set_document(
            Document(text=self._output_text, cursor_position=len(self._output_text)),
            bypass_readonly=True,
        )

    def _append_output(self, text: str) -> None:
        """向输出区追加文本。

        若 spinner 动画在转，则把新文本插到 spinner 之前（spinner 保持末尾），
        避免工具通知等内容把动画顶掉。
        """
        if self._spinner_active:
            self._output_text = (
                self._output_text[: self._spinner_pos]
                + text
                + self._output_text[self._spinner_pos :]
            )
            self._spinner_pos += len(text)
        else:
            self._output_text += text
        self._set_output_document()

    def _start_spinner(self) -> None:
        """在输出区末尾启动盲文加载动画（幂等）。"""
        if self._spinner_active:
            return
        self._spinner_active = True
        self._spinner_pos = len(self._output_text)
        self._append_output(_SPINNER_FRAMES[0])  # 插入首个动画帧
        self.app.create_background_task(self._spin())

    def _stop_spinner(self) -> None:
        """移除输出区末尾的 spinner 动画（首个内容 delta 到达时调用）。"""
        if not self._spinner_active:
            return
        self._spinner_active = False
        # 去掉末尾的 spinner 字符（上次插入的一帧）
        self._output_text = self._output_text[: self._spinner_pos]
        self._set_output_document()

    async def _spin(self) -> None:
        """盲文 spinner 动画循环：每帧替换末尾字符，直到 _stop_spinner。"""
        frame = 0
        while self._spinner_active:
            ch = _SPINNER_FRAMES[frame % len(_SPINNER_FRAMES)]
            self._output_text = (
                self._output_text[: self._spinner_pos]
                + ch
                + self._output_text[self._spinner_pos + 1 :]
            )
            self._set_output_document()
            self.app.invalidate()
            frame += 1
            await asyncio.sleep(_SPINNER_INTERVAL)

    def _build_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("c-c")
        def _exit(_event) -> None:
            self.app.exit()

        # Enter 发送（默认多行模式下 Enter 是换行，需覆盖为发送）
        # ~in_paste_mode：粘贴多行文本时让默认绑定把换行当文本插入，不误发送
        @kb.add("enter", filter=~in_paste_mode)
        def _send(_event) -> None:
            _event.current_buffer.validate_and_handle()

        # Shift+Enter 换行：终端需支持 CSI-u 扩展（kitty/wezterm/foot 等），
        # 序列为 ESC[13;2u；不支持 CSI-u 的终端该键与 Enter 无法区分
        @kb.add("escape", "[", "1", "3", ";", "2", "u")
        def _shift_enter(event) -> None:
            event.current_buffer.insert_text("\n")

        # Alt+Enter 换行：CSI-u 不支持时的兜底
        @kb.add("escape", "c-m")
        def _alt_enter(event) -> None:
            event.current_buffer.insert_text("\n")

        @kb.add("escape")
        def _esc(_event) -> None:
            if not self._generating:
                return
            now = time.monotonic()
            if now - self._last_esc < _ESC_DOUBLE_GAP:
                self._cancel_event.set()
                self._append_output("\n[已中断本次回复]\n")
            else:
                self._last_esc = now
                self._append_output("\n[再按一次 ESC 终止输出]\n")

        return kb

    # --- 发送消息 ---
    def _on_accept(self, buffer: Buffer) -> bool:
        """Enter 时触发：发送消息或执行指令。

        返回 False：让 validate_and_handle 在 accept_handler 执行后
        自动清空输入框并写入历史。
        """
        if self._generating:
            return False
        text = buffer.text.strip()
        if not text:
            return False
        parsed = parse_command(text)
        if parsed is not None:
            result = self.session.run_command(parsed)
            self._append_output(f"{PROMPT_USER}{text}\n")
            if result.quit:
                self.app.exit()
                return False
            if result.clear:
                self._clear_output()
            if result.text:
                self._append_output(f"{result.text}\n")
            return False
        self._append_output(f"{PROMPT_USER}{text}\n")
        self._start_generation(text)
        return False

    def _clear_output(self) -> None:
        """清空输出区（仅视觉，不影响对话历史）。"""
        self._stop_spinner()  # 避免残留动画帧在清屏后继续替换
        self._output_text = ""
        self.output_area.buffer.set_document(
            Document(text="", cursor_position=0),
            bypass_readonly=True,
        )
    def _start_generation(self, text: str) -> None:
        self._generating = True
        self.input_area.read_only = True
        self._cancel_event.clear()
        self._append_output(PROMPT_ARIS)
        self._start_spinner()  # 等待首字期间显示盲文加载动画
        threading.Thread(target=self._generate, args=(text,), daemon=True).start()
        self.app.create_background_task(self._consume())

    def _generate(self, text: str) -> None:
        """后台线程：流式生成，把增量/工具通知放入队列，结束后放入 None。"""

        def _notice(name: str, result: str) -> None:
            # on_tool 回调（本线程执行）：只入队，界面更新由 _consume 完成
            self._delta_queue.put(ToolNotice(name=name, result=result))

        try:
            for delta in self.session.ask(
                text,
                should_stop=lambda: self._cancel_event.is_set(),
                on_tool=_notice,
            ):
                self._delta_queue.put(delta)
        finally:
            self._delta_queue.put(None)  # 结束标记

    async def _consume(self) -> None:
        """UI 侧：消费队列，更新输出区（文本增量 / 工具通知），结束后解锁输入。"""
        loop = asyncio.get_running_loop()
        while True:
            item = await loop.run_in_executor(None, self._delta_queue.get)
            if item is None:
                break
            if isinstance(item, ToolNotice):
                # 工具调用独立成行显示（不重复 Aris 提示符），spinner 继续转
                self._append_output(f"\n  [调用工具 {item.name} → {item.result[:60]}]\n")
            else:
                self._stop_spinner()  # 首个内容 delta：移除加载动画
                self._append_output(item)
            self.app.invalidate()
        self._stop_spinner()
        self._append_output("\n")
        self._generating = False
        self.input_area.read_only = False
        self.app.invalidate()

    # --- 入口 ---
    def run(self) -> int:
        try:
            self.app.run()
        finally:
            self.session.close()  # 释放浏览器等会话资源
        return 0
