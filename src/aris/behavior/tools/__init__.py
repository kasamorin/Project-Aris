"""内置工具集：统一入口注册全部内置工具。"""

from __future__ import annotations

from ..browser import BrowserManager
from ..registry import ToolRegistry
from . import get_current_time, web_search


def register_builtin_tools(
    registry: ToolRegistry, browser: BrowserManager | None = None
) -> None:
    """把全部内置工具注册进给定 registry。

    browser 由调用方注入（chat 会话持有一个 BrowserManager，实现浏览器
    会话内常驻）；为 None 时联网搜索工具内部惰性自建浏览器。
    """
    get_current_time.register(registry)
    web_search.register(registry, browser=browser)
