"""store 模块测试（二）：迁移机制与 pgvector helper。

单元用例全程无外部依赖（用假连接记录 SQL）；向量往返用例需要真实 PostgreSQL，
未运行时自动跳过（`aris db start` 后再跑即可覆盖）。
"""

from __future__ import annotations

from contextlib import closing, nullcontext

import pytest

from aris.store import migrate, vector
from aris.store.migrate import Migration, MigrationError
from aris.store.vector import VectorError, quote_ident, to_vector_literal


# ---------------------------------------------------------------------------
# 迁移机制（假连接：只验证编排逻辑，不碰真库）
# ---------------------------------------------------------------------------


class _FakeCursor:
    """极简假游标：只服务于 migrate 用到的两条语句。"""

    def __init__(self, conn: "_FakeConn") -> None:
        self.conn = conn
        self._rows: list[tuple[str, int, str]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: object = None) -> None:
        normalized = " ".join(sql.split())
        self.conn.statements.append(normalized)
        if normalized.startswith("SELECT owner, version, name"):
            self._rows = [(o, v, n) for (o, v), n in self.conn.applied.items()]

    def fetchall(self) -> list[tuple[str, int, str]]:
        return self._rows


class _FakeConn:
    """假连接：记录 SQL，并在 INSERT 跟踪表时更新已应用集合。"""

    def __init__(self) -> None:
        self.applied: dict[tuple[str, int], str] = {}
        self.statements: list[str] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def execute(self, sql: str, params: tuple | None = None) -> None:
        normalized = " ".join(sql.split())
        self.statements.append(normalized)
        # 跟踪表名大小写不敏感：SQL 里是小写，故统一转大写再比对
        if normalized.upper().startswith("INSERT INTO STORE_SCHEMA_MIGRATIONS") and params:
            self.applied[(params[0], params[1])] = params[2]

    def transaction(self):
        return nullcontext()

    def commit(self) -> None:
        """迁移流程会在关键点提交（否则 conn.transaction() 退化成 SAVEPOINT）；假连接只记账。"""
        self.statements.append("COMMIT")


def test_migration_runner_applies_in_version_order_and_is_idempotent():
    """乱序登记也按版本执行；重复运行不再应用（幂等）。

    用 ``migrations=`` 显式传入，避免往全局登记表塞测试迁移（否则同进程后续
    用例的 drift 校验会被带偏）。
    """
    executed: list[str] = []
    first = Migration("test_order", 1, "first", lambda _c: executed.append("v1"))
    second = Migration("test_order", 2, "second", lambda _c: executed.append("v2"))
    migrations = [second, first]  # 故意乱序

    conn = _FakeConn()
    assert migrate.run(conn, migrations=migrations) == ["test_order:001", "test_order:002"]
    assert executed == ["v1", "v2"]
    assert migrate.run(conn, migrations=migrations) == []
    assert migrate.pending_ids(conn, migrations=migrations) == []


def test_migration_failure_is_not_recorded():
    """迁移抛错时整体失败且不写入跟踪表（不留半截 schema）。"""

    def boom(_conn: object) -> None:
        raise RuntimeError("DDL 出错")

    migrations = [Migration("test_fail", 1, "boom", boom)]
    conn = _FakeConn()
    with pytest.raises(MigrationError):
        migrate.run(conn, migrations=migrations)
    assert ("test_fail", 1) not in conn.applied


def test_migration_drift_detected():
    """已应用的迁移被改名 → 快速失败（防止 schema 漂移）。"""
    conn = _FakeConn()
    conn.applied[("test_drift", 1)] = "original"  # 伪造"已应用"

    renamed = [Migration("test_drift", 1, "renamed", lambda _c: None)]
    with pytest.raises(MigrationError):
        migrate.pending_ids(conn, migrations=renamed)


def test_real_migrations_have_unique_versions_per_owner():
    """真实模块登记的迁移版本号不重复（测试迁移走 migrations= 传参，不进全局表）。"""
    seen: set[tuple[str, int]] = set()
    for m in migrate.all_migrations():
        assert (m.owner, m.version) not in seen, f"重复版本 {m.id}"
        seen.add((m.owner, m.version))


# ---------------------------------------------------------------------------
# 向量 helper：参数校验（无数据库）
# ---------------------------------------------------------------------------


def test_quote_ident_accepts_valid_and_rejects_injection():
    assert quote_ident("knowledge_chunks") == '"knowledge_chunks"'
    for bad in ("chunks; DROP TABLE x", "1abc", "", "a-b", 'a"b', "a b"):
        with pytest.raises(VectorError):
            quote_ident(bad)


def test_to_vector_literal_format():
    assert to_vector_literal([1, 0.5, -2]) == "[1,0.5,-2]"
    with pytest.raises(VectorError):
        to_vector_literal([])


def test_search_rejects_unknown_distance_and_bad_limit():
    with pytest.raises(VectorError):
        vector.search(object(), "t", [0.1, 0.2], distance="hamming")
    with pytest.raises(VectorError):
        vector.search(object(), "t", [0.1, 0.2], limit=0)


# ---------------------------------------------------------------------------
# 向量 helper：真实数据库往返（PG 未运行则跳过）
# ---------------------------------------------------------------------------


def _pg_available() -> bool:
    """本机便携实例是否在运行（用于决定是否跑集成用例）。"""
    try:
        from aris.store import detect, is_running

        return is_running(detect())
    except Exception:  # 探针失败一律视为不可用，避免收集期报错
        return False


requires_pg = pytest.mark.skipif(not _pg_available(), reason="PostgreSQL 未运行（先 aris db start）")


@requires_pg
def test_vector_roundtrip_upsert_search_filter_and_index():
    """临时表上跑通：建索引 → upsert → 近邻检索 → 过滤 → 维度读取。"""
    from aris.store.db import connect

    with closing(connect()) as conn:
        conn.execute(
            "CREATE TEMP TABLE tvec (id text PRIMARY KEY, embedding vector(3), note text)"
        )
        rows = [
            {"id": "a", "embedding": [1.0, 0.0, 0.0], "note": "x"},
            {"id": "b", "embedding": [0.0, 1.0, 0.0], "note": "y"},
            {"id": "c", "embedding": [0.0, 0.0, 1.0], "note": "z"},
        ]
        assert vector.upsert(conn, "tvec", rows) == 3
        assert vector.count(conn, "tvec") == 3
        assert vector.table_dimension(conn, "tvec") == 3

        index_name = vector.ensure_index(conn, "tvec")
        assert index_name == "tvec_embedding_hnsw"

        hits = vector.search(conn, "tvec", [0.9, 0.1, 0.0], limit=2)
        assert [h["id"] for h in hits] == ["a", "b"]
        assert hits[0]["distance"] < hits[1]["distance"]

        # upsert 幂等：同 id 覆盖，不新增
        vector.upsert(conn, "tvec", [{"id": "a", "embedding": [0.0, 0.0, 1.0], "note": "x2"}])
        assert vector.count(conn, "tvec") == 3

        filtered = vector.search(conn, "tvec", [0.0, 0.0, 1.0], where="note = %s", params=["y"])
        assert [h["id"] for h in filtered] == ["b"]

        with pytest.raises(VectorError):
            vector.search(conn, "tvec; DROP TABLE tvec", [0.0, 0.0, 1.0])
