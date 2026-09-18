"""轻量迁移机制：按「模块 + 版本」记录并顺序应用 DDL。

自研不引框架（见 AGENTS.md「记忆实现方式」）。设计取舍：

- 迁移以 **Python 函数** 形式登记（而非 .sql 文件）：需要按参数建表
  （如向量维度来自 provider），Python 里直接可算，且不必配 package-data；
- 每个迁移**单独一个事务**：PostgreSQL 的 DDL 可回滚，失败即整条回退，
  不留半截 schema（核心逻辑快速失败，见 AGENTS.md「错误处理」）；
- 归属用 `owner` 区分（`store` / `knowledge` / `memory` 各自登记自己的迁移），
  记录表按 `(owner, version)` 唯一，互不干扰；
- 已应用的迁移**不允许改名**：同一 `(owner, version)` 名字对不上即报错，
  防止"改了历史迁移但没重放"造成的 schema 漂移。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:  # 仅类型标注用，运行时不导入 psycopg
    from psycopg import Connection

TRACKING_TABLE = "store_schema_migrations"

_TRACKING_DDL = f"""
CREATE TABLE IF NOT EXISTS {TRACKING_TABLE} (
    owner      text        NOT NULL,
    version    integer     NOT NULL,
    name       text        NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (owner, version)
)
"""


class MigrationError(RuntimeError):
    """迁移相关错误（登记冲突 / 历史迁移被改写 / 执行失败）。"""


@dataclass(frozen=True)
class Migration:
    """一条迁移：`owner` 内版本递增，`up` 只做 DDL。"""

    owner: str
    version: int
    name: str
    up: Callable[[Connection], None]

    @property
    def id(self) -> str:
        """稳定标识，如 ``knowledge:003``。"""
        return f"{self.owner}:{self.version:03d}"


@dataclass
class _Registry:
    """迁移登记表（按 owner 去重，便于模块重复 import 时幂等）。"""

    by_owner: dict[str, list[Migration]] = field(default_factory=dict)

    def add(self, migrations: Iterable[Migration]) -> None:
        for m in migrations:
            bucket = self.by_owner.setdefault(m.owner, [])
            if m not in bucket:
                bucket.append(m)

    def all(self) -> list[Migration]:
        """全部迁移，按 (owner, version) 升序。"""
        return sorted(
            (m for bucket in self.by_owner.values() for m in bucket),
            key=lambda m: (m.owner, m.version),
        )


_registry = _Registry()


def register(migrations: Sequence[Migration] | Migration) -> None:
    """登记迁移（模块 import 时调用，可重复调用）。"""
    items = [migrations] if isinstance(migrations, Migration) else list(migrations)
    _registry.add(items)


def all_migrations() -> list[Migration]:
    """返回已登记的全部迁移（测试与自检用）。"""
    return _registry.all()


def _applied(conn: Connection) -> dict[tuple[str, int], str]:
    """已应用迁移：(owner, version) → name。"""
    with conn.cursor() as cur:
        cur.execute(f"SELECT owner, version, name FROM {TRACKING_TABLE}")
        return {(row[0], row[1]): row[2] for row in cur.fetchall()}


def _ensure_tracking(conn: Connection) -> None:
    """建跟踪表并**立刻提交**。

    提交很关键：psycopg 的 ``conn.transaction()`` 在已有隐式事务时会退化成
    SAVEPOINT，不提交就等于「迁移跑完即回滚」（实测踩到：迁移报成功但表不存在）。
    """
    with conn.cursor() as cur:
        cur.execute(_TRACKING_DDL)
    conn.commit()


def _check_drift(applied: dict[tuple[str, int], str]) -> None:
    """已应用的迁移被改写（同名版本换了名字）时快速失败。"""
    for m in all_migrations():
        recorded = applied.get((m.owner, m.version))
        if recorded is not None and recorded != m.name:
            raise MigrationError(
                f"迁移 {m.id} 已应用为「{recorded}」，但当前代码里叫「{m.name}」——"
                "历史迁移不可改写，请新增版本号"
            )


def pending(conn: Connection | None = None) -> list[Migration]:
    """尚未应用的迁移（升序）。"""
    from .db import connect

    target = conn or connect()
    _ensure_tracking(target)
    applied = _applied(target)
    _check_drift(applied)
    return [m for m in all_migrations() if (m.owner, m.version) not in applied]


def pending_ids(conn: Connection | None = None) -> list[str]:
    """尚未应用的迁移 id 列表。"""
    return [m.id for m in pending(conn)]


def run(conn: Connection | None = None) -> list[str]:
    """应用全部待执行迁移，返回本次实际应用的 id 列表（幂等）。"""
    from .db import connect

    target = conn or connect()
    _ensure_tracking(target)
    todos = pending(target)
    target.commit()  # 清掉查询留下的隐式事务，保证下面每条迁移都是独立事务
    done: list[str] = []
    for m in todos:
        logger.info(f"应用迁移 {m.id} {m.name}")
        try:
            # 每条迁移一个事务：失败则整条回滚，不留半截 schema
            with target.transaction():
                m.up(target)
                target.execute(
                    f"INSERT INTO {TRACKING_TABLE} (owner, version, name) "
                    "VALUES (%s, %s, %s)",
                    (m.owner, m.version, m.name),
                )
        except Exception as exc:
            raise MigrationError(f"迁移 {m.id} 执行失败：{exc}") from exc
        done.append(m.id)
    if done:
        target.commit()  # 交给调用方前确保落盘（DDL 已提交，此处是保险）
        logger.success(f"迁移完成，应用 {len(done)} 条：{', '.join(done)}")
    else:
        logger.info("schema 已是最新，无需迁移")
    return done


def applied_at(conn: Connection) -> dict[str, datetime]:
    """已应用迁移 → 时间（运维排查用）。"""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT owner, version, applied_at FROM {TRACKING_TABLE} "
            "ORDER BY applied_at"
        )
        return {f"{owner}:{version:03d}": ts for owner, version, ts in cur.fetchall()}
