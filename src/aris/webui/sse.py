"""SSE 实时推送模块——loguru sink + 审计推送 + 客户端管理。

为审计流水和日志查看页面提供 SSE 实时数据流。
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from collections import deque
from typing import Any

from loguru import logger


class SSEBroker:
    """SSE 事件广播器——维护客户端队列，广播日志/审计事件。"""

    def __init__(self, buffer_size: int = 200) -> None:
        self._clients: list[queue.Queue[str]] = []
        self._lock = threading.Lock()
        # 最近 N 条事件缓冲（新客户端连接时可补发）
        self._buffer: deque[str] = deque(maxlen=buffer_size)

    def subscribe(self) -> queue.Queue[str]:
        """订阅事件流，返回一个 Queue。"""
        q: queue.Queue[str] = queue.Queue(maxsize=500)
        with self._lock:
            self._clients.append(q)
            # 补发最近的事件
            for event in self._buffer:
                q.put_nowait(event)
        return q

    def unsubscribe(self, q: queue.Queue[str]) -> None:
        """取消订阅。"""
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    def broadcast(self, event: str) -> None:
        """广播一条 SSE 事件到所有客户端。"""
        with self._lock:
            self._buffer.append(event)
            dead: list[queue.Queue[str]] = []
            for client in self._clients:
                try:
                    client.put_nowait(event)
                except queue.Full:
                    dead.append(client)
            for d in dead:
                self._clients.remove(d)

    @property
    def client_count(self) -> int:
        """当前在线客户端数。"""
        with self._lock:
            return len(self._clients)


# 全局 broker 实例
log_broker = SSEBroker()
audit_broker = SSEBroker()


def loguru_log_sink(message: Any) -> None:
    """loguru sink：把日志 record 推送到 log_broker。"""
    record = message.record
    data = {
        "ts": record["time"].isoformat(timespec="milliseconds"),
        "level": record["level"].name,
        "module": record["name"],
        "message": record["message"],
    }
    event = f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
    log_broker.broadcast(event)


def audit_push(target: str, duration: float, ok: bool = True, detail: str = "") -> None:
    """推送审计事件到 audit_broker。"""
    import time
    data = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "target": target,
        "duration_ms": round(duration * 1000, 1),
        "ok": ok,
        "detail": detail,
    }
    event = f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
    audit_broker.broadcast(event)


# 防止重复安装
_sink_installed = False


def install_loguru_sink() -> None:
    """安装 loguru SSE sink（仅安装一次）。"""
    global _sink_installed
    if _sink_installed:
        return
    _sink_installed = True
    logger.add(
        loguru_log_sink,
        format="{message}",
        level="DEBUG",
        filter=lambda record: record["name"].startswith("aris"),
    )
