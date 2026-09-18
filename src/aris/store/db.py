"""数据库连接与探活（psycopg 3）。

只负责「拿到连接」与「探活」，不含业务语义：业务表由上层模块（`knowledge/` /
`memory/`）自己的迁移定义，本模块提供建表与检索的公共 helper 时同样保持中立。
"""

from __future__ import annotations

from typing import Any

from .pgenv import PgEnv, detect


def connect(env: PgEnv | None = None, *, register_vector: bool = True):
    """建立数据库连接（调用方负责关闭；返回 psycopg.Connection）。

    默认注册 pgvector 适配器：此后 Python 列表可直接读写 ``vector`` 列，
    不必手工拼字面量。扩展未建或适配包缺失时自动降级（不影响普通 SQL）。
    """
    try:
        import psycopg
    except ImportError as exc:  # 依赖缺失属环境问题，给出可读提示
        raise RuntimeError("缺少 psycopg 依赖，请先运行 uv sync") from exc
    conn = psycopg.connect((env or detect()).dsn)
    if register_vector:
        from .vector import register_adapters

        register_adapters(conn)
    return conn


def health(env: PgEnv | None = None) -> dict[str, Any]:
    """探活：返回服务端版本、``vector`` 扩展版本、当前库与连接串。"""
    target = env or detect()
    with connect(target) as conn:
        with conn.cursor() as cur:
            cur.execute("SHOW server_version")
            server_version = cur.fetchone()[0]
            cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            row = cur.fetchone()
            cur.execute("SELECT current_database()")
            database = cur.fetchone()[0]
    return {
        "server_version": server_version,
        "vector_version": row[0] if row else None,
        "database": database,
        "dsn": target.dsn,
    }
