"""审计统计层：记录统一通讯层（bus）的调用/事件流水。

设计动机（对应架构商讨结论）：
- 所有模块间通讯都经过 core.bus，bus 在此记录「谁调谁、何时、耗时、次数」，
  为将来 WebUI / 调试提供查询接口。
- 曾考虑用 C 实现统计通道，后否决：统计只需元数据、不涉及消息内容，
  Python 层足够（KISS + 轮子哲学），C 继续只做性能敏感点。

实现要点：
- 内存环形缓冲（定长 _MAX_RECORDS），只保留最近 N 条，防内存膨胀。
- 记录失败静默降级（try/except 包裹），绝不拖累业务调用。
- 线程安全：多线程（如将来 auto 定时任务模块）并发记录/查询均加锁。
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

# 环形缓冲上限：最多保留的流水条数（防内存膨胀）
_MAX_RECORDS = 2000


@dataclass
class AuditRecord:
    """一条通讯审计记录。"""

    kind: str          # "call"（服务调用）/ "event"（事件发布）
    target: str        # 服务名（如 llm.stream）或事件名（如 memory.saved）
    ts: float          # 记录时间戳（monotonic 秒）
    duration: float    # 本次调用耗时（秒）
    ok: bool = True    # 是否成功（服务调用抛异常时为 False）
    detail: str = ""   # 附加信息（如调用方模块名）


class AuditLog:
    """审计流水存储：环形缓冲 + 聚合查询。"""

    def __init__(self, max_records: int = _MAX_RECORDS) -> None:
        self._records: deque[AuditRecord] = deque(maxlen=max_records)
        self._lock = threading.Lock()

    def record(
        self,
        *,
        kind: str,
        target: str,
        duration: float,
        ok: bool = True,
        detail: str = "",
    ) -> None:
        """记录一条流水。内部绝不抛异常（静默降级）。"""
        try:
            with self._lock:
                self._records.append(
                    AuditRecord(
                        kind=kind,
                        target=target,
                        ts=monotonic(),
                        duration=duration,
                        ok=ok,
                        detail=detail,
                    )
                )
        except Exception:
            pass  # 审计失败不影响业务

    def recent(self, limit: int = 50) -> list[AuditRecord]:
        """取最近的流水（新→旧），供调试/查询。"""
        with self._lock:
            return list(self._records)[-limit:][::-1]

    def summary(self) -> dict[str, Any]:
        """聚合统计：按目标聚合并返回可序列化结果，供 WebUI 等消费。"""
        calls: dict[str, dict] = {}
        events: dict[str, dict] = {}
        with self._lock:
            records = list(self._records)
        for r in records:
            agg = calls if r.kind == "call" else events
            bucket = agg.setdefault(r.target, {"count": 0, "total_ms": 0.0, "errors": 0})
            bucket["count"] += 1
            bucket["total_ms"] += r.duration * 1000.0
            if not r.ok:
                bucket["errors"] += 1
        for bucket in calls.values():
            bucket["avg_ms"] = (
                round(bucket["total_ms"] / bucket["count"], 3) if bucket["count"] else 0.0
            )
        return {
            "calls": calls,
            "events": events,
            "total": len(records),
        }


# 全局单例：bus 直接 import 使用，避免每处自行实例化
default_audit = AuditLog()


def audit_call(target: str, duration: float, ok: bool = True, detail: str = "") -> None:
    """记录一次服务调用。"""
    default_audit.record(kind="call", target=target, duration=duration, ok=ok, detail=detail)


def audit_event(target: str, duration: float, ok: bool = True, detail: str = "") -> None:
    """记录一次事件发布。"""
    default_audit.record(kind="event", target=target, duration=duration, ok=ok, detail=detail)


def query_recent(limit: int = 50) -> list[AuditRecord]:
    """查询最近流水。"""
    return default_audit.recent(limit=limit)


def query_summary() -> dict[str, Any]:
    """查询聚合统计。"""
    return default_audit.summary()
