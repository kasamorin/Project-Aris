"""知识库建表迁移（import 本模块即登记，由 `store.migrate` 统一执行）。

表结构定案见 developDoc/KNOWLEDGE-BASE.md 5.2：

- 两张表：`knowledge_docs`（文档级，记 hash / mtime / 状态）+
  `knowledge_chunks`（块级，含 384 维向量）；
- 增量策略是 **content hash 幂等 + 软删重建**，故删除一律走 `deleted_at`；
- **向量维度取自 provider**（C1：本地 Bekko 384），建表时写死进 `vector(n)`；
  换维度 = 重建该表 + 重摄入（业务侧有维度校验兜底）；
- `knowledge_chunks` **冗余 source_path / title**：检索只查这一张表即可返回
  可引用信息，不必 join（引用标识是知识库的存在意义，D3 定案）。
"""

from __future__ import annotations

from typing import Any

from ..store.migrate import Migration, register

DOCS_TABLE = "knowledge_docs"
CHUNKS_TABLE = "knowledge_chunks"
OWNER = "knowledge"


def embedding_dimension() -> int:
    """当前 embedding provider 的维度（不加载模型，仅读 provider 元数据）。"""
    from ..store.embedding import get_provider

    return get_provider().dimension


def _create_docs(conn: Any) -> None:
    """文档表 + 「同一路径只允许一个活跃版本」的部分唯一索引。"""
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {DOCS_TABLE} (
            doc_id       uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
            source_path  text        NOT NULL,
            title        text        NOT NULL DEFAULT '',
            content_hash text        NOT NULL,
            byte_size    bigint      NOT NULL DEFAULT 0,
            source_mtime timestamptz,
            chunk_count  integer     NOT NULL DEFAULT 0,
            meta         jsonb       NOT NULL DEFAULT '{{}}'::jsonb,
            ingested_at  timestamptz NOT NULL DEFAULT now(),
            deleted_at   timestamptz
        )
        """
    )
    conn.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {DOCS_TABLE}_path_active_uniq "
        f"ON {DOCS_TABLE} (source_path) WHERE deleted_at IS NULL"
    )


def _create_chunks(conn: Any) -> None:
    """块表（含向量列）+ 检索常用索引。"""
    dimension = embedding_dimension()
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {CHUNKS_TABLE} (
            chunk_id     bigserial   PRIMARY KEY,
            doc_id       uuid        NOT NULL REFERENCES {DOCS_TABLE}(doc_id)
                                     ON DELETE CASCADE,
            chunk_index  integer     NOT NULL,
            source_path  text        NOT NULL,
            title        text        NOT NULL DEFAULT '',
            heading_path text        NOT NULL DEFAULT '',
            content      text        NOT NULL,
            content_hash text        NOT NULL,
            char_count   integer     NOT NULL,
            embedding    vector({dimension}) NOT NULL,
            meta         jsonb       NOT NULL DEFAULT '{{}}'::jsonb,
            created_at   timestamptz NOT NULL DEFAULT now(),
            deleted_at   timestamptz
        )
        """
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS {CHUNKS_TABLE}_doc_id_idx ON {CHUNKS_TABLE} (doc_id)"
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS {CHUNKS_TABLE}_active_idx "
        f"ON {CHUNKS_TABLE} (deleted_at)"
    )


register(
    [
        Migration(OWNER, 1, "create knowledge_docs", _create_docs),
        Migration(OWNER, 2, "create knowledge_chunks", _create_chunks),
    ]
)
