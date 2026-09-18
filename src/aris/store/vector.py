"""pgvector 通用 helper：建索引、写入、检索、维度读取。

只做**通用动作**，不含业务语义：表名、过滤条件、top-k 策略都由调用方给
（知识库的检索语义在 `knowledge/`，记忆的在 `memory/`）。

安全约定：表名/列名/索引名经 :func:`quote_ident` 校验后插值，其余参数一律走
占位符；距离算子与 opclass 走白名单——不留任何可以拼 SQL 的口子。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from loguru import logger

# 合法标识符（表名 / 列名 / 索引名）
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# 距离算子：pgvector 的 <-> L2、<=> cosine、<#> 内积（返回负内积）
_OPS = {"cosine": "<=>", "l2": "<->", "inner_product": "<#>"}

# 允许的索引 opclass（与距离算子对应）
_OPCLASSES = frozenset(
    {
        "vector_cosine_ops",
        "vector_l2_ops",
        "vector_ip_ops",
        "halfvec_cosine_ops",
        "halfvec_l2_ops",
        "halfvec_ip_ops",
    }
)

# HNSW 默认参数（先用 pgvector 默认值跑通，再按数据量调）
DEFAULT_M = 16
DEFAULT_EF_CONSTRUCTION = 64
DEFAULT_EF_SEARCH = 40


class VectorError(ValueError):
    """向量 helper 的参数/使用错误（非法标识符、未知算子、维度不符等）。"""


def quote_ident(name: str) -> str:
    """校验并引用标识符；非法名直接报错（不静默转义）。"""
    if not isinstance(name, str) or not _IDENTIFIER.match(name):
        raise VectorError(f"非法标识符: {name!r}（只允许字母/数字/下划线，且不以数字开头）")
    return f'"{name}"'


def to_vector_literal(values: Sequence[float]) -> str:
    """把 Python 序列转成 pgvector 字面量 ``[1,2,3]``（写入时配合 ``::vector``）。"""
    if len(values) == 0:
        raise VectorError("空向量无法写入")
    return "[" + ",".join(f"{float(v):.8g}" for v in values) + "]"


def register_adapters(conn: Any) -> bool:
    """注册 pgvector 的 psycopg 适配器（无则返回 False，仅影响自动转换）。"""
    try:
        from pgvector.psycopg import register_vector
    except ImportError:  # 可选依赖缺失：读写仍可用字面量方式
        logger.debug("未安装 pgvector 适配包，向量按字面量处理")
        return False
    try:
        register_vector(conn)
    except Exception as exc:  # 扩展未建或数据库不支持时不该阻塞连接
        logger.debug(f"注册 vector 适配器失败（可能未建扩展）: {exc}")
        return False
    return True


def table_dimension(conn: Any, table: str, column: str = "embedding") -> int | None:
    """读某表向量列的维度；列不存在或不是 ``vector(n)`` 时返回 None。

    维度定案见 developDoc/KNOWLEDGE-BASE.md 5.2（C1）：换维度 = 重建该表 + 重摄入，
    故调用方应先读维度再决定是否建表。
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            WHERE c.relname = %s AND a.attname = %s AND a.attnum > 0
            """,
            (table, column),
        )
        row = cur.fetchone()
    if not row or not row[0]:
        return None
    matched = re.fullmatch(r"vector\((\d+)\)", row[0])
    return int(matched.group(1)) if matched else None


def ensure_index(
    conn: Any,
    table: str,
    column: str = "embedding",
    *,
    distance: str = "cosine",
    m: int = DEFAULT_M,
    ef_construction: int = DEFAULT_EF_CONSTRUCTION,
) -> str:
    """建 HNSW 索引（已存在则跳过），返回索引名。

    与定案一致：**先导数据、后建索引**（HNSW 空表也能建，但先导后建更快）。
    """
    opclass = {
        "cosine": "vector_cosine_ops",
        "l2": "vector_l2_ops",
        "inner_product": "vector_ip_ops",
    }.get(distance)
    if opclass is None or opclass not in _OPCLASSES:
        raise VectorError(f"未知距离算子: {distance!r}（可用 {sorted(_OPS)}）")
    if m <= 0 or ef_construction <= 0:
        raise VectorError("m / ef_construction 必须为正整数")

    table_sql = quote_ident(table)
    column_sql = quote_ident(column)
    index_name = f"{table}_{column}_hnsw"
    index_sql = quote_ident(index_name)
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS {index_sql} ON {table_sql} "
        f"USING hnsw ({column_sql} {opclass}) "
        f"WITH (m = {int(m)}, ef_construction = {int(ef_construction)})"
    )
    return index_name


def upsert(
    conn: Any,
    table: str,
    rows: Sequence[dict[str, Any]],
    *,
    conflict_key: str = "id",
) -> int:
    """按主键 upsert 若干行（值为序列的字段按 vector 处理），返回影响行数。"""
    if not rows:
        return 0
    columns = list(rows[0].keys())
    if not columns:
        raise VectorError("upsert 的行不能为空字典")
    for row in rows:
        if list(row.keys()) != columns:
            raise VectorError("upsert 各行的字段必须完全一致")

    conflict_sql = quote_ident(conflict_key)
    if conflict_key not in columns:
        raise VectorError(f"conflict_key {conflict_key!r} 不在字段中：{columns}")

    placeholders: list[str] = []
    values: list[Any] = []
    for row in rows:
        row_ph = []
        for col in columns:
            value = row[col]
            if isinstance(value, (list, tuple)):
                row_ph.append("%s::vector")
                values.append(to_vector_literal(value))
            else:
                row_ph.append("%s")
                values.append(value)
        placeholders.append("(" + ", ".join(row_ph) + ")")

    updates = ", ".join(
        f"{quote_ident(c)} = EXCLUDED.{quote_ident(c)}" for c in columns if c != conflict_key
    )
    sql = (
        f"INSERT INTO {quote_ident(table)} "
        f"({', '.join(quote_ident(c) for c in columns)}) "
        f"VALUES {', '.join(placeholders)} "
        f"ON CONFLICT ({conflict_sql}) DO UPDATE SET {updates}"
        if updates
        else f"INSERT INTO {quote_ident(table)} "
        f"({', '.join(quote_ident(c) for c in columns)}) "
        f"VALUES {', '.join(placeholders)} "
        f"ON CONFLICT ({conflict_sql}) DO NOTHING"
    )
    with conn.cursor() as cur:
        cur.execute(sql, values)
        return cur.rowcount or 0


def search(
    conn: Any,
    table: str,
    query: Sequence[float],
    *,
    limit: int = 5,
    column: str = "embedding",
    distance: str = "cosine",
    select: Sequence[str] = ("*",),
    where: str | None = None,
    params: Sequence[Any] = (),
    ef_search: int | None = DEFAULT_EF_SEARCH,
) -> list[dict[str, Any]]:
    """向量近邻检索，返回带 ``distance`` 字段的行（按距离升序）。

    ``where`` 由调用方提供且必须自带占位符（如 ``"deleted_at IS NULL AND doc_id = %s"``），
    其参数放 ``params``。
    """
    op = _OPS.get(distance)
    if op is None:
        raise VectorError(f"未知距离算子: {distance!r}（可用 {sorted(_OPS)}）")
    if limit <= 0:
        raise VectorError("limit 必须为正整数")

    from psycopg.rows import dict_row

    select_sql = ", ".join("*" if c == "*" else quote_ident(c) for c in select)
    sql = (
        f"SELECT {select_sql}, {quote_ident(column)} {op} %s::vector AS distance "
        f"FROM {quote_ident(table)}"
    )
    if where:
        sql += f" WHERE {where}"
    sql += " ORDER BY distance LIMIT %s"
    values: list[Any] = [to_vector_literal(query), *params, int(limit)]

    with conn.cursor(row_factory=dict_row) as cur:
        if ef_search is not None:
            # SET 不接受占位符，故强转 int 后插值（参数已校验为整数）
            cur.execute(f"SET LOCAL hnsw.ef_search = {int(ef_search)}")
        cur.execute(sql, values)
        return list(cur.fetchall())


def count(conn: Any, table: str, *, where: str | None = None, params: Sequence[Any] = ()) -> int:
    """统计行数（``where`` 规则同 :func:`search`）。"""
    sql = f"SELECT count(*) FROM {quote_ident(table)}"
    if where:
        sql += f" WHERE {where}"
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        row = cur.fetchone()
        return int(row[0]) if row else 0
