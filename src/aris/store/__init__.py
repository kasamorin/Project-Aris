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
- ``store.start`` / ``store.stop`` —— 启动编排用（确保可用并迁移；只停自己拉起的实例）
- ``store.embed_preload`` / ``store.embed_status`` —— 后台预热与就绪状态

实现进度：环境探测、便携实例获取、连接与探活、embedding 抽象与本地 provider、
迁移机制与向量检索 helper 均已就位；落地首个业务表时即可验证端到端。
"""

from __future__ import annotations

from contextlib import closing
from threading import Thread
from typing import Any

from loguru import logger

from ..core import provide
from .bootstrap import (
    BootstrapError,
    bootstrap_env,
    ensure_database,
    is_running,
    start,
    stop,
)
from .conf import StoreConfig, get_store_config
from .embedding import EmbeddingError, EmbeddingProvider, get_provider
from .pgenv import PgEnv, PgSource, detect


def _embed_dimension() -> int:
    """总线服务：当前 embedding provider 的向量维度（建表前要先问它）。"""
    return get_provider().dimension


def _connect() -> Any:
    """总线服务：提供一个数据库连接（调用方负责关闭）。

    边界：**「怎么连」由 store 决定**（DSN / 适配器 / 探针），但业务模块自己的
    建表与业务 SQL 归各模块所有——它们经此服务取连接后自行执行，不再各自
    处理 DSN 与凭据。
    """
    from .db import connect

    return connect()


def _health() -> dict[str, Any]:
    """总线服务：数据库探活。"""
    from .db import health

    return health(detect())


def _embed(texts: list[str]) -> list[list[float]]:
    """总线服务：文本 → 向量（provider 懒加载，未装重依赖时报可读错误）。"""
    return get_provider().embed(texts)


def _migrate_run() -> list[str]:
    """总线服务：应用全部待执行迁移，返回本次应用的 id。"""
    from .db import connect
    from .migrate import run

    with closing(connect()) as conn:
        return run(conn)


def _migrate_pending() -> list[str]:
    """总线服务：列出待执行迁移 id。"""
    from .db import connect
    from .migrate import pending_ids

    with closing(connect()) as conn:
        return pending_ids(conn)


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


def _vector_count(table: str, **options: Any) -> int:
    """总线服务：统计行数（options 见 store.vector.count，如 where/params）。"""
    from .db import connect
    from .vector import count

    with closing(connect()) as conn:
        return count(conn, table, **options)


# 启动编排（serve）用状态：实例是否由本次 serve 自启（退出时只停自己拉起的），
# embedding 预热进度（idle / warming / ready / failed / skipped）
_db_started_by_serve = False
_embed_state: dict[str, Any] = {"status": "idle", "detail": "未预热"}


def _db_status() -> dict[str, Any]:
    """总线服务：数据库实例状态（只读，不启动任何东西）。

    供 `aris serve` 的探针与将来的状态面板区分三种情形：未初始化 / 未运行 / 在跑。
    """
    env = detect()
    installed = bool(env.installed and (env.pgdata / "PG_VERSION").exists())
    running = is_running(env) if installed else False
    pending: list[str] = []
    if running:
        pending = _migrate_pending()
    return {
        "installed": installed,
        "running": running,
        "port": env.port,
        "started_by_serve": _db_started_by_serve,
        "pending_migrations": pending,
    }


def _start(*, autostart: bool = True) -> dict[str, Any]:
    """总线服务：确保数据库可用（按需自启便携实例）并应用迁移（serve 启动步骤）。"""
    global _db_started_by_serve
    env = detect()
    if not env.installed or not (env.pgdata / "PG_VERSION").exists():
        raise BootstrapError("便携数据库尚未初始化：先执行 `aris db init`")
    running = is_running(env)
    if not running:
        if not autostart:
            raise BootstrapError("数据库未运行，且已禁用自启：先执行 `aris db start`")
        logger.info("数据库未运行，正在自启便携实例 ...")
        start(env)
        _db_started_by_serve = True
    ensure_database(env)  # 幂等：建库 + 建 vector 扩展
    applied = _migrate_run()
    return {
        "running_before": running,
        "started_by_serve": _db_started_by_serve,
        "port": env.port,
        "migrations": applied,
    }


def _stop(*, only_self_started: bool = True) -> bool:
    """总线服务：停止数据库；默认只停「本次 serve 自启的」，原本在跑的不动。"""
    global _db_started_by_serve
    if only_self_started and not _db_started_by_serve:
        return False
    stopped = stop(detect())
    _db_started_by_serve = False
    return stopped


def _embed_preload() -> dict[str, Any]:
    """总线服务：后台预热 embedding（立即返回，不阻塞启动流程）。

    懒加载会让首个检索/工具调用等约 20s，容易顶穿调用方 timeout；本地模型
    反正迟早要常驻，故由 serve 在启动阶段就放到后台线程去加载。预热失败不致命
    （真正调用时会重试加载并抛出可读错误）。
    """
    if _embed_state["status"] in ("warming", "ready"):
        return dict(_embed_state)
    provider = get_provider()
    warmup = getattr(provider, "warmup", None)
    if warmup is None:  # 未来云端 provider 无需预热
        _embed_state.update(status="skipped", detail=f"{provider.name} 无需预热")
        return dict(_embed_state)
    _embed_state.update(status="warming", detail=f"{provider.name} 预热中")

    def _work() -> None:
        try:
            warmup()
        except Exception as exc:  # 预热失败只记日志，不阻断 serve
            logger.warning(f"embedding 预热失败：{exc}")
            _embed_state.update(status="failed", detail=str(exc))
        else:
            logger.success(f"embedding 预热就绪：{provider.name}（{provider.dimension} 维）")
            _embed_state.update(
                status="ready", detail=f"{provider.name}（{provider.dimension} 维）"
            )

    Thread(target=_work, name="aris-embed-preload", daemon=True).start()
    return dict(_embed_state)


def _embed_status() -> dict[str, Any]:
    """总线服务：embedding 预热状态（不触发加载）。"""
    return dict(_embed_state)


provide("store.health", _health)
provide("store.embed", _embed)
provide("store.embed_dimension", _embed_dimension)
provide("store.connect", _connect)
provide("store.migrate.run", _migrate_run)
provide("store.migrate.pending", _migrate_pending)
provide("store.vector.search", _vector_search)
provide("store.vector.upsert", _vector_upsert)
provide("store.vector.ensure_index", _vector_ensure_index)
provide("store.vector.dimension", _vector_dimension)
provide("store.vector.count", _vector_count)
provide("store.start", _start)
provide("store.db_status", _db_status)
provide("store.stop", _stop)
provide("store.embed_preload", _embed_preload)
provide("store.embed_status", _embed_status)

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
