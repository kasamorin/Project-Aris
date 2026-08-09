"""内置工具：get_current_time —— 获取当前日期时间。

返回结构化信息（年/月/日/时/分/秒/星期/时区分离），模型按需提取表达。
"""

from __future__ import annotations

import datetime

from ..registry import ToolRegistry


def _get_current_time() -> dict:
    """返回当前日期时间各组成部分及本地时区偏移。"""
    now = datetime.datetime.now().astimezone()
    offset = now.strftime("%z")
    return {
        "year": now.year,
        "month": now.month,
        "day": now.day,
        "hour": now.hour,
        "minute": now.minute,
        "second": now.second,
        "weekday": now.strftime("%A"),
        "weekday_cn": "星期" + "一二三四五六日"[now.weekday()],
        "iso_weekday": now.isoweekday(),
        "timezone": f"{offset[:3]}:{offset[3:]}",
    }


def register(registry: ToolRegistry) -> None:
    """向 registry 注册 get_current_time 工具。"""
    registry.register(
        "get_current_time",
        description="获取当前日期和时间（年/月/日/时/分/秒/星期（含中英文及 ISO 数字编号）/时区偏移）",
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        fn=_get_current_time,
    )
