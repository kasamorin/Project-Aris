"""知识库业务：摄入 / 列举 / 移除 / 检索 / 建索引。

对外只经总线（CMCB）暴露 `knowledge.*` 服务；底层一律通过 `store.*` 使用
embedding 与数据库（跨模块不允许直接 import，见 AGENTS.md「模块间调用规则」）。

增量策略（B4 定案）：**content hash 幂等 + 软删重建**——同路径文件 hash 未变
则跳过；变了则把旧的文档与块软删（`deleted_at`）后整篇重建。
"""

from __future__ import annotations

import hashlib
import re
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from ..core import call
from .chunking import chunk_document
from .conf import KnowledgeConfig, get_knowledge_config
from .loaders import SUPPORTED_SUFFIXES, LoadError, iter_files, load_document
from .migrations import CHUNKS_TABLE, DOCS_TABLE

STATUS_ADDED = "added"
STATUS_UPDATED = "updated"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

# 文件名里不允许出现的字符（路径分隔符与控制字符）
_FILENAME_UNSAFE = re.compile(r"[\\/\x00-\x1f]")
MAX_FILENAME_CHARS = 200


class KnowledgeError(RuntimeError):
    """知识库业务错误（未启用 / 维度不符 / 参数非法）。"""


def safe_filename(raw: str) -> str:
    """把上传文件名收敛成安全的落盘名（只保留基名）。

    防穿越三道：① 取 basename，去掉任何目录部分；② 替换剩余分隔符与控制字符；
    ③ 调用方落盘前再确认目标路径确实在目标目录内（纵深防御）。
    """
    name = Path(str(raw or "")).name
    name = _FILENAME_UNSAFE.sub("_", name).strip()
    if not name or name in {".", ".."}:
        raise KnowledgeError(f"非法的文件名：{raw!r}")
    if len(name) > MAX_FILENAME_CHARS:
        raise KnowledgeError(f"文件名过长（>{MAX_FILENAME_CHARS} 字符）：{name[:40]}…")
    return name


@dataclass(frozen=True)
class IngestOutcome:
    """单文件摄入结果。"""

    path: str
    status: str
    chunks: int
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        """转成可打印/可序列化的字典。"""
        return {
            "path": self.path,
            "status": self.status,
            "chunks": self.chunks,
            "reason": self.reason,
        }


class KnowledgeService:
    """知识库业务实现（无状态，可随时构造；数据库连接每次调用现取）。"""

    def __init__(self, config: KnowledgeConfig | None = None) -> None:
        self._config = config or get_knowledge_config()

    @property
    def config(self) -> KnowledgeConfig:
        """当前配置。"""
        return self._config

    # ------------------------------------------------------------------
    # schema
    # ------------------------------------------------------------------

    def ensure_schema(self) -> None:
        """确保表已建（幂等），并校验表维度与当前 provider 是否一致。"""
        call("store.migrate.run")
        table_dim = call("store.vector.dimension", CHUNKS_TABLE)
        provider_dim = call("store.embed_dimension")
        if table_dim is not None and table_dim != provider_dim:
            raise KnowledgeError(
                f"{CHUNKS_TABLE} 的向量维度是 {table_dim}，当前 provider 是 {provider_dim}："
                "换维度需重建该表并重新摄入（KNOWLEDGE-BASE.md 5.2 C1）"
            )

    def ensure_index(self) -> str:
        """建 HNSW 索引（幂等）。定案要求先导数据后建索引，故在摄入结束时调用。"""
        return call(
            "store.vector.ensure_index",
            CHUNKS_TABLE,
            "embedding",
            distance="cosine",
            m=self._config.index_m,
            ef_construction=self._config.index_ef_construction,
        )

    # ------------------------------------------------------------------
    # 摄入
    # ------------------------------------------------------------------

    def ingest(self, targets: list[str]) -> list[dict[str, Any]]:
        """摄入文件或目录（目录递归）；返回每个文件的处理结果。"""
        if not self._config.enabled:
            raise KnowledgeError(
                "知识库已关闭（config/knowledge.toml 的 enabled=false），摄入被拒绝"
            )
        if not targets:
            raise KnowledgeError("至少要给一个文件或目录路径")

        self.ensure_schema()
        files = iter_files([Path(t) for t in targets])
        if not files:
            logger.warning("目标目录下没有可摄入的文件（支持 md / txt / html）")

        outcomes: list[IngestOutcome] = []
        for path in files:
            try:
                outcomes.append(self._ingest_one(path))
            except LoadError as exc:  # 单个文件的问题不拖垮整批
                logger.warning(f"跳过 {path}：{exc}")
                outcomes.append(
                    IngestOutcome(str(path), STATUS_FAILED, 0, reason=str(exc))
                )

        if any(o.status in (STATUS_ADDED, STATUS_UPDATED) for o in outcomes):
            self.ensure_index()
        return [o.as_dict() for o in outcomes]

    def _ingest_one(self, path: Path) -> IngestOutcome:
        """单文件摄入：hash 未变跳过，变了则软删重建。"""
        doc = load_document(path)
        source_path = str(path.resolve())

        with closing(call("store.connect")) as conn:
            with conn.transaction():
                existing = conn.execute(
                    f"SELECT doc_id, content_hash FROM {DOCS_TABLE} "
                    "WHERE source_path = %s AND deleted_at IS NULL",
                    (source_path,),
                ).fetchone()
                if existing and existing[1] == doc.content_hash:
                    return IngestOutcome(source_path, STATUS_SKIPPED, 0, reason="内容未变")

                chunks = chunk_document(
                    doc.text,
                    kind=doc.kind,
                    max_chars=self._config.max_chars,
                    min_chars=self._config.min_chars,
                    overlap_ratio=self._config.overlap_ratio,
                )
                if not chunks:
                    raise LoadError(f"没有切出任何块：{path.name}（正文过短或全为空行）")

                vectors = call("store.embed", [c.embed_text for c in chunks])
                if len(vectors) != len(chunks):
                    raise KnowledgeError(
                        f"embedding 返回 {len(vectors)} 条，与块数 {len(chunks)} 不一致"
                    )

                if existing:
                    conn.execute(
                        f"UPDATE {DOCS_TABLE} SET deleted_at = now() WHERE doc_id = %s",
                        (existing[0],),
                    )
                    conn.execute(
                        f"UPDATE {CHUNKS_TABLE} SET deleted_at = now() WHERE doc_id = %s",
                        (existing[0],),
                    )

                row = conn.execute(
                    f"INSERT INTO {DOCS_TABLE} "
                    "(source_path, title, content_hash, byte_size, source_mtime, chunk_count) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING doc_id",
                    (
                        source_path,
                        doc.title,
                        doc.content_hash,
                        doc.byte_size,
                        doc.mtime,
                        len(chunks),
                    ),
                ).fetchone()
                doc_id = row[0]

                for chunk, vector in zip(chunks, vectors, strict=True):
                    conn.execute(
                        f"INSERT INTO {CHUNKS_TABLE} "
                        "(doc_id, chunk_index, source_path, title, heading_path, "
                        " content, content_hash, char_count, embedding) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            doc_id,
                            chunk.index,
                            source_path,
                            doc.title,
                            chunk.heading_path,
                            chunk.content,
                            hashlib.sha256(chunk.content.encode("utf-8")).hexdigest(),
                            chunk.char_count,
                            vector,
                        ),
                    )

        status = STATUS_UPDATED if existing else STATUS_ADDED
        logger.info(f"{status}：{source_path}（{len(chunks)} 块）")
        return IngestOutcome(source_path, status, len(chunks))

    # ------------------------------------------------------------------
    # 上传（WebUI）
    # ------------------------------------------------------------------

    def upload_root(self) -> Path:
        """上传文件的落盘目录（配置为空时用 ``<data_dir>/knowledge``）。"""
        if self._config.upload_dir:
            return Path(self._config.upload_dir).expanduser().resolve()
        from ..config import get_settings

        return Path(get_settings().data_dir).resolve() / "knowledge"

    def upload(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """保存上传文件并摄入（同名覆盖）。

        ``items``：``[{"filename": str, "data": bytes}]``。落盘是为了让
        ``source_path`` 稳定可引用、可重摄（见 KNOWLEDGE-BASE.md 的 B3 决定）。
        单个文件的问题不拖垮整批：失败项以 ``status=failed`` 返回。
        """
        if not self._config.enabled:
            raise KnowledgeError(
                "知识库已关闭（config/knowledge.toml 的 enabled=false），上传被拒绝"
            )
        if not items:
            raise KnowledgeError("没有收到文件")
        if len(items) > self._config.max_files_per_upload:
            raise KnowledgeError(
                f"单次最多 {self._config.max_files_per_upload} 个文件，收到 {len(items)} 个"
            )

        root = self.upload_root()
        root.mkdir(parents=True, exist_ok=True)
        saved: list[str] = []
        failures: list[dict[str, Any]] = []
        limit_mb = self._config.max_file_bytes // (1024 * 1024)

        for item in items:
            raw_name = str(item.get("filename", ""))
            data = item.get("data") or b""
            try:
                name = safe_filename(raw_name)
                if Path(name).suffix.lower() not in SUPPORTED_SUFFIXES:
                    supported = "，".join(sorted(SUPPORTED_SUFFIXES))
                    raise KnowledgeError(f"不支持的格式：{name}（支持 {supported}）")
                if not data:
                    raise KnowledgeError(f"文件为空：{name}")
                if len(data) > self._config.max_file_bytes:
                    raise KnowledgeError(f"文件超过 {limit_mb}MB 上限：{name}")

                target = (root / name).resolve()
                if target.parent != root:  # 纵深防御：basename 之后仍再确认一次
                    raise KnowledgeError(f"非法落盘路径：{name}")
                target.write_bytes(data)
                saved.append(str(target))
            except (KnowledgeError, OSError) as exc:
                logger.warning(f"上传失败 {raw_name}：{exc}")
                failures.append(
                    IngestOutcome(raw_name, STATUS_FAILED, 0, reason=str(exc)).as_dict()
                )

        return (self.ingest(saved) if saved else []) + failures

    def status(self) -> dict[str, Any]:
        """给管理后台用的状态摘要（开关 / 上传限制 / 文档与块计数）。"""
        info: dict[str, Any] = {
            "enabled": self._config.enabled,
            "upload_dir": str(self.upload_root()),
            "max_file_bytes": self._config.max_file_bytes,
            "max_files_per_upload": self._config.max_files_per_upload,
            "top_k": self._config.top_k,
            "docs": 0,
            "chunks": 0,
            "error": "",
        }
        try:
            self.ensure_schema()
            info["docs"] = len(self.list_sources())
            info["chunks"] = int(
                call("store.vector.count", CHUNKS_TABLE, where="deleted_at IS NULL")
            )
        except Exception as exc:  # 状态查询不该因数据库未就绪而让页面 500
            logger.warning(f"知识库状态查询失败：{exc}")
            info["error"] = str(exc)
        return info

    # ------------------------------------------------------------------
    # 列举 / 移除
    # ------------------------------------------------------------------

    def list_sources(self) -> list[dict[str, Any]]:
        """列出所有活跃文档（新→旧）。"""
        with closing(call("store.connect")) as conn:
            rows = conn.execute(
                f"SELECT source_path, title, chunk_count, byte_size, ingested_at "
                f"FROM {DOCS_TABLE} WHERE deleted_at IS NULL ORDER BY ingested_at DESC"
            ).fetchall()
        return [
            {
                "source_path": r[0],
                "title": r[1],
                "chunks": r[2],
                "bytes": r[3],
                "ingested_at": r[4],
            }
            for r in rows
        ]

    def remove(self, source_path: str) -> dict[str, Any]:
        """软删一个文档及其全部块（可重新摄入恢复）。"""
        key = str(Path(source_path).expanduser().resolve())
        with closing(call("store.connect")) as conn:
            with conn.transaction():
                row = conn.execute(
                    f"SELECT doc_id, chunk_count FROM {DOCS_TABLE} "
                    "WHERE source_path = %s AND deleted_at IS NULL",
                    (key,),
                ).fetchone()
                if row is None:
                    return {"source_path": key, "removed": 0, "chunks": 0}
                conn.execute(
                    f"UPDATE {CHUNKS_TABLE} SET deleted_at = now() WHERE doc_id = %s",
                    (row[0],),
                )
                conn.execute(
                    f"UPDATE {DOCS_TABLE} SET deleted_at = now() WHERE doc_id = %s",
                    (row[0],),
                )
        logger.info(f"已移除：{key}（{row[1]} 块）")
        return {"source_path": key, "removed": 1, "chunks": row[1]}

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int | None = None) -> dict[str, Any]:
        """纯向量近邻检索（D2 第一阶段），返回带来源标识的结果。"""
        if not self._config.enabled:
            logger.warning("知识库已关闭（enabled=false），检索返回空结果")
            return {"query": query, "results": [], "enabled": False}
        if not query.strip():
            raise KnowledgeError("检索词不能为空")

        self.ensure_schema()
        vector = call("store.embed", [query])[0]
        rows = call(
            "store.vector.search",
            CHUNKS_TABLE,
            vector,
            limit=int(limit or self._config.top_k),
            select=("chunk_index", "source_path", "title", "heading_path", "content"),
            where="deleted_at IS NULL",
            ef_search=self._config.ef_search,
        )
        results = [
            {
                "id": index + 1,
                "source_path": row["source_path"],
                "title": row["title"],
                "heading_path": row["heading_path"],
                "chunk_index": row["chunk_index"],
                "content": row["content"],
                "distance": float(row["distance"]),
            }
            for index, row in enumerate(rows)
        ]
        logger.debug(f"检索「{query}」命中 {len(results)} 块")
        return {"query": query, "results": results, "enabled": True}


_service: KnowledgeService | None = None


def get_service() -> KnowledgeService:
    """知识库服务单例（配置只在首次构造时读一次）。"""
    global _service
    if _service is None:
        _service = KnowledgeService()
    return _service
