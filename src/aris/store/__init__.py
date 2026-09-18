"""store 模块 —— 存储与向量基础设施（PostgreSQL + embedding）。

定位（2026-09-18 定案，见 developDoc/KNOWLEDGE-BASE.md 第 4.1 节）：

- embedding 抽象与 PostgreSQL/pgvector 基础设施（DSN、连接、迁移、向量检索 helper）
  都收在本模块，供 `knowledge/` / `memory/` 复用，避免两套连接与迁移；
- **不认识**业务模块，不做业务语义——依赖方向恒为「业务 →（总线）→ store」。

总线服务：
- ``store.health`` —— 数据库探活（服务端版本 / vector 扩展版本 / 当前库）
- ``store.embed`` —— 文本 → 向量（懒加载本地 provider）
- ``store.migrate.run`` / ``store.migrate.pending`` —— 迁移执行与待办查询
- ``store.vector.search`` / ``upsert`` / ``ensure_index`` / ``dimension`` ——
  pgvector 通用动作（业务语义留在 `knowledge/` / `memory/`）

实现进度：环境探测、便携实例获取、连接与探活、embedding 抽象与本地 provider、
迁移机制与向量检索 helper 均已就位；落地首个业务表时即可验证端到端。
"""

from __future__ import annotations

from contextlib import closing
from typing import Any

from ..core import provide
from .bootstrap import (
    BootstrapError,
    bootstrap_env,
    is_running,
    start,
    stop,
)
from .conf import StoreConfig, get_store_config
from .embedding import EmbeddingError, EmbeddingProvider, get_provider
from .pgenv import PgEnv, PgSource, detect


def _health() -> dict[str, Any]:
    """总线服务：数据库探活。"""
    from .db import health

    return health(detect())


def _embed(texts: list[str]) -> list[list[float]]:
    """总线服务：文本 → 向量（provider 懒加载，未装重依赖时报可读错误）。"""
    return get_provider().embed(texts)


def _migrate_run() -> list[str]:
    """总线服务：应用全部待执行迁移，返回本次应用的 id。"""
    from .migrate import run

    return run()


def _migrate_pending() -> list[str]:
    """总线服务：列出待执行迁移 id。"""
    from .migrate import pending_ids

    return pending_ids()


def _vector_search(table: str, query: list[float], **options: Any) -> list[dict[str, Any]]:
    """总线服务：向量近邻检索（参数见 store.vector.search）。"""
    from .db import connect
    from .vector import search

    with closing(connect()) as conn:
        return search(conn, table, query, **options)


def _vector_upsert(table: str, rows: list[dict[str, Any]], **options: Any) -> int:
    """总线服务：按主键 upsert（序列字段按 vector 处理），返回影响行数。"""
    from .db import connect
    from .vector import upsert

    with closing(connect()) as conn:
        affected = upsert(conn, table, rows, **options)
        conn.commit()
        return affected


def _vector_ensure_index(table: str, column: str = "embedding", **options: Any) -> str:
    """总线服务：建 HNSW 索引（幂等），返回索引名。"""
    from .db import connect
    from .vector import ensure_index

    with closing(connect()) as conn:
        name = ensure_index(conn, table, column, **options)
        conn.commit()
        return name


def _vector_dimension(table: str, column: str = "embedding") -> int | None:
    """总线服务：读某表向量列维度（换维度 = 重建表 + 重摄入，见 C1 定案）。"""
    from .db import connect
    from .vector import table_dimension

    with closing(connect()) as conn:
        return table_dimension(conn, table, column)


provide("store.health", _health)
provide("store.embed", _embed)
provide("store.migrate.run", _migrate_run)
provide("store.migrate.pending", _migrate_pending)
provide("store.vector.search", _vector_search)
provide("store.vector.upsert", _vector_upsert)
provide("store.vector.ensure_index", _vector_ensure_index)
provide("store.vector.dimension", _vector_dimension)

__all__ = [
    "BootstrapError",
    "EmbeddingError",
    "EmbeddingProvider",
    "PgEnv",
    "PgSource",
    "StoreConfig",
    "bootstrap_env",
    "detect",
    "get_provider",
    "get_store_config",
    "is_running",
    "start",
    "stop",
]
