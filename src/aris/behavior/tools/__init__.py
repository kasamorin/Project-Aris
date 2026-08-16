"""内置工具集：统一入口注册全部内置工具。"""

from __future__ import annotations

from ..registry import ToolRegistry
from . import get_current_time, http_request, web_search


def register_builtin_tools(registry: ToolRegistry) -> None:
    """把全部内置工具注册进给定 registry。"""
    get_current_time.register(registry)
    http_request.register(registry)
    web_search.register(registry)
