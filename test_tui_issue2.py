"""验证 TUI 状态行修复：内容输出后工具提示不再覆盖，且不紧贴。"""
import sys
sys.path.insert(0, "/home/morin/Codes/Project-Aris/src")

from aris.chat.tui import ChatTUI, ToolNotice
from aris.chat.commands import PROMPT_ARIS


class MockSession:
    """模拟会话：不真正调用 LLM，只供 ChatTUI 构造。"""

    def __init__(self):
        pass

    def run_command(self, parsed):
        from aris.chat.commands import ParsedCommand
        return None

    def close(self):
        pass


def simulate():
    tui = ChatTUI(MockSession())
    # 手动驱动状态机，模拟 _start_generation 的前半段
    tui._generating = True
    tui._append_output(PROMPT_ARIS)
    tui._state_active = True
    tui._state_start = len(tui._output_text)
    tui._tool_name = ""
    tui._spinner_char = "⠋"

    # 场景1：先内容后工具（问题复现场景）
    # 首个内容 delta
    tui._clear_state_line()
    tui._append_output("我搜一下")
    # 工具通知
    tui._show_tool("web_search")
    # 工具后内容
    tui._append_output("这是搜索到的结果")
    print("场景1 最终输出:", repr(tui._output_text))
    assert "我搜一下" in tui._output_text, "内容不应被覆盖"
    assert tui._output_text.index("我搜一下") < tui._output_text.index("web_search"), "工具提示应在内容之后"
    assert "\n  [调用工具: web_search]\n" in tui._output_text, "工具提示应独立成行"
    assert "这是搜索到的结果" in tui._output_text

    # 场景2：先工具后内容（状态行活跃时，同行显示工具名，不新增行）
    tui2 = ChatTUI(MockSession())
    tui2._generating = True
    tui2._append_output(PROMPT_ARIS)
    tui2._state_active = True
    tui2._state_start = len(tui2._output_text)
    tui2._tool_name = ""
    tui2._spinner_char = "⠋"
    tui2._show_tool("get_current_time")
    assert tui2._state_active, "等待首字时状态行应保持活跃"
    mid = tui2._output_text
    print("场景2 工具后中间态:", repr(mid))
    assert mid.endswith("⠋ 工具调用: get_current_time"), "工具名应显示在状态行"
    # 首个内容 delta 清除状态行
    tui2._clear_state_line()
    tui2._append_output("现在是")
    print("场景2 最终输出:", repr(tui2._output_text))
    assert tui2._output_text.endswith(PROMPT_ARIS + "现在是"), "状态行应被清除，保留 Aris: 前缀"

    print("ALL PASS")


simulate()
