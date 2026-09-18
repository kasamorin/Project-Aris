"""store 模块 —— 存储与向量基础设施（PostgreSQL + embedding）。

定位（2026-09-18 定案，见 developDoc/KNOWLEDGE-BASE.md 第 4.1 节）：

- embedding 抽象与 PostgreSQL/pgvector 基础设施（DSN、连接、迁移、向量检索 helper）
  都收在本模块，供 `knowledge/` / `memory/` 复用，避免两套连接与迁移；
- **不认识**业务模块，不做业务语义——依赖方向恒为「业务 →（总线）→ store」。

总线服务：
- ``store.health`` —— 数据库探活（服务端版本 / vector 扩展版本 / 当前库）

实现进度：环境探测（`pgenv`）、便携实例获取（`bootstrap`）、连接与探活（`db`）
已就位；embedding 抽象、迁移与向量检索 helper 待后续。
"""

from __future__ import annotations

from typing import Any

from ..core import provide
from .bootstrap import (
    BootstrapError,
    bootstrap,
    is_running,
    start,
    stop,
)
from .pgenv import PgEnv, PgSource, detect


def _health() -> dict[str, Any]:
    """总线服务：数据库探活。"""
    from .db import health

    return health(detect())


provide("store.health", _health)

__all__ = [
    "BootstrapError",
    "PgEnv",
    "PgSource",
    "bootstrap",
    "detect",
    "is_running",
    "start",
    "stop",
]
