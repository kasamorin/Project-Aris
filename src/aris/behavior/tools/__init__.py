"""内置工具集：统一入口注册全部内置工具。"""

from __future__ import annotations

from . import now
from ..registry import ToolRegistry


def register_builtin_tools(registry: ToolRegistry) -> None:
    """把全部内置工具注册进给定 registry。"""
    now.register(registry)
