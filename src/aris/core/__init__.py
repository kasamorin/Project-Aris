"""core 模块 —— Agent 核心与统一通讯层。

职责：
- bus：统一通讯层（服务注册表 + 事件总线 + 审计统计），所有模块间通讯
  统一经 `core.call` / `core.emit` 进出，模块间不直接互相 import。
- llm：LLM 提供方抽象（可插拔）+ 连接编排（fallback / 超时 / 错误处理）。

对外便捷入口（统一前缀 core.）：
- provide / call：服务注册与调用（同步、一对一）
- subscribe / emit：事件订阅与发布（一对多、解耦）
- query_recent / query_summary：审计流水与聚合统计查询
"""

from . import audit
from . import http
from .bus import (
    call,
    emit,
    has_service,
    provide,
    query_recent,
    query_summary,
    subscribe,
)

__all__ = [
    "audit",
    "call",
    "emit",
    "has_service",
    "provide",
    "query_recent",
    "query_summary",
    "subscribe",
]
