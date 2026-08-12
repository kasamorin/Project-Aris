"""错误广播：提醒用户 Aris 出现问题。

桌面弹窗（notify-send）为当前实现，手机推送等留注册接口。
广播失败只记日志，绝不抛异常（宽容降级）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

from loguru import logger

from aris.cfgtoml import load_config

# 广播处理器：title, message -> None。可通过 register_push 注册手机推送等。
PushHandler = Callable[[str, str], None]

_handlers: list[PushHandler] = []

# Linux 常规默认运行时目录；非 Linux 或无法探测时退化为空
if hasattr(os, "getuid"):
    _DEFAULT_XDG_RUNTIME_DIR = f"/run/user/{os.getuid()}"
else:
    _DEFAULT_XDG_RUNTIME_DIR = ""


@dataclass
class NotifyConfig:
    """桌面通知可调参数（config/notify.toml）。"""

    timeout_seconds: float = 5.0


_notify_config = load_config(NotifyConfig(), "notify.toml")


def register_push(handler: PushHandler) -> None:
    """注册额外推送渠道（如手机通知），与桌面弹窗并存。"""
    _handlers.append(handler)


def broadcast(title: str, message: str) -> None:
    """向所有渠道广播错误提醒（桌面弹窗 + 已注册的推送）。"""
    _desktop_notify(title, message)
    for handler in _handlers:
        try:
            handler(title, message)
        except Exception as e:  # 广播失败不拖累主流程
            logger.warning(f"推送渠道 {handler.__name__} 发送失败: {e}")


def _desktop_notify(title: str, message: str) -> None:
    """通过 notify-send 弹桌面通知；不可用时静默降级。"""
    if not shutil.which("notify-send"):
        logger.debug("notify-send 不可用，跳过桌面弹窗")
        return
    try:
        subprocess.run(
            ["notify-send", "--urgency=critical", "--app-name=Aris", title, message],
            check=False,
            timeout=_notify_config.timeout_seconds,
            env={
                **os.environ,
                "XDG_RUNTIME_DIR": os.environ.get(
                    "XDG_RUNTIME_DIR", _DEFAULT_XDG_RUNTIME_DIR
                ),
            },
        )
    except Exception as e:
        logger.warning(f"桌面弹窗失败: {e}")
