"""统一通讯层（bus）：服务注册表 + 事件总线。

所有模块间通讯（同步调用 / 事件广播）统一经过这里，达成：
1. **解耦**：模块间不直接 import，只通过 `core.call` / `core.emit` 交互，
   后期加模块（auto 定时任务等）不必彼此引用。
2. **可观测**：每次调用/事件记入审计（core.audit），供调试与将来 WebUI 查询。
3. **健壮性**：服务不存在返回可读错误 + 模糊建议；审计失败不影响业务调用。

命名规范（`module.service` / `module.event` 两级）：
- 服务：`llm.stream`、`tools.execute`、`loop.run`
- 事件：`memory.saved`、`voice.ready`（规划）

调用方用 `from aris.core import call, emit, provide, subscribe`。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from difflib import get_close_matches
from time import monotonic
from typing import Any

from loguru import logger

from . import audit

# 已注册的服务：服务名 → 可调用对象
_services: dict[str, Callable[..., Any]] = {}
_services_lock = threading.Lock()

# 已订阅的事件：事件名 → 处理器列表
_subscribers: dict[str, list[Callable[[Any], None]]] = {}
_subscribers_lock = threading.Lock()


def provide(service: str, fn: Callable[..., Any]) -> None:
    """注册一个服务（同步调用，可有返回值）。

    重名注册时覆盖旧实现并记警告（幂等重注册场景：模块重载/热替换）。
    """
    with _services_lock:
        if service in _services:
            logger.warning(f"服务 {service} 被重复注册，覆盖旧实现")
        _services[service] = fn


def call(service: str, *args: Any, **kwargs: Any) -> Any:
    """调用一个已注册的服务，返回其返回值。

    服务不存在时记日志并返回 None（宽容降级，不抛到上层）。
    执行抛异常时记审计（ok=False）后原样抛出。
    """
    with _services_lock:
        fn = _services.get(service)
    if fn is None:
        _report_missing("服务", service, list(_services))
        return None
    start = monotonic()
    try:
        result = fn(*args, **kwargs)
        audit.audit_call(service, monotonic() - start)
        return result
    except Exception:
        audit.audit_call(service, monotonic() - start, ok=False)
        raise


def subscribe(event: str, handler: Callable[[Any], None]) -> None:
    """订阅一个事件：事件发布时同步调用 handler(payload)。"""
    with _subscribers_lock:
        _subscribers.setdefault(event, []).append(handler)


def emit(event: str, payload: Any = None) -> None:
    """发布一个事件：同步调用所有订阅者。

    无订阅者时静默丢弃（事件是松耦合通知，不强求必须有接收方）。
    单个订阅者抛异常不影响其他订阅者（宽容降级）。
    """
    with _subscribers_lock:
        handlers = list(_subscribers.get(event, ()))
    if not handlers:
        return
    start = monotonic()
    try:
        for handler in handlers:
            try:
                handler(payload)
            except Exception as e:
                logger.warning(f"事件 {event} 的处理器 {handler.__name__} 异常: {e}")
        audit.audit_event(event, monotonic() - start)
    except Exception:
        audit.audit_event(event, monotonic() - start, ok=False)


def query_recent(limit: int = 50) -> list[audit.AuditRecord]:
    """查询最近审计流水（新→旧）。"""
    return audit.query_recent(limit=limit)


def query_summary() -> dict[str, Any]:
    """查询聚合统计（按目标合并）。"""
    return audit.query_summary()


def _report_missing(kind: str, target: str, known: list[str]) -> None:
    """记录「目标不存在」日志，并给出最相近的已注册目标作为提示。"""
    close = get_close_matches(target, known, n=3, cutoff=0.5)
    hint = f"，是不是想调用: {', '.join(close)}" if close else ""
    logger.error(f"{kind} {target} 未注册{hint}")
