"""内置工具：get_current_time —— 获取当前日期时间。

返回结构化信息（日期/时间/星期分离），模型按需提取表达。
"""

from __future__ import annotations

import datetime

from ..registry import ToolRegistry


def _get_current_time() -> dict:
    """返回当前日期时间各部分（本地时区）。"""
    now = datetime.datetime.now()
    return {
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": now.strftime("%A"),
    }


def register(registry: ToolRegistry) -> None:
    """向 registry 注册 get_current_time 工具。"""
    registry.register(
        "get_current_time",
        description="获取当前日期和时间（含星期）",
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        fn=_get_current_time,
    )
