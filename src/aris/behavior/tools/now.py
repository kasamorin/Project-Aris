"""内置工具：now —— 获取当前日期时间。

首个内置工具，不依赖外部服务，用于验证「函数调用」完整链路。
"""

from __future__ import annotations

import datetime

from ..registry import ToolRegistry


def _now() -> str:
    """返回当前日期时间（本地时区，含星期）。"""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")


def register(registry: ToolRegistry) -> None:
    """向 registry 注册 now 工具。"""
    registry.register(
        "now",
        description="获取当前日期和时间",
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        fn=_now,
    )
