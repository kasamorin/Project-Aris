"""knowledge 模块 —— 知识库（面向外部资料的独立 RAG 检索）。

定位与全部定案见 developDoc/KNOWLEDGE-BASE.md。本模块只做业务：
**摄入（md / txt / html）→ 分块 → 入库 → 纯向量检索**；embedding 与数据库
设施一律经总线使用 `store/*`（依赖方向恒为 `knowledge → 总线 → store`）。

总线服务：
- ``knowledge.ingest`` —— 摄入文件或目录，返回逐文件结果
- ``knowledge.sources`` —— 列出已摄入文档
- ``knowledge.remove`` —— 软删一个文档及其块
- ``knowledge.search`` —— 纯向量检索（带来源标识）
- ``knowledge.reindex`` —— 建 HNSW 索引（幂等）

启用开关：`config/knowledge.toml` 的 ``enabled``。

尚未实现（后续）：agent 工具 `knowledge_search`（D1）、WebUI 上传（B3 第二阶段）。
"""

from __future__ import annotations

from typing import Any

from ..core import provide
from . import migrations  # noqa: F401  —— import 即登记建表迁移
from .conf import KnowledgeConfig, get_knowledge_config
from .service import KnowledgeError, KnowledgeService, get_service

_service = get_service()

provide("knowledge.ingest", _service.ingest)
provide("knowledge.sources", _service.list_sources)
provide("knowledge.remove", _service.remove)
provide("knowledge.search", _service.search)
provide("knowledge.reindex", _service.ensure_index)
provide("knowledge.upload", _service.upload)
provide("knowledge.status", _service.status)


def _start() -> dict[str, Any]:
    """总线服务：确保知识库 schema 与索引就绪（serve 启动步骤）。

    库不可用时**快速失败**（抛 KnowledgeError）：serve 按 optional 步骤记 warning
    并继续启动其余模块，不静默降级（见 developDoc/SERVE.md 第 5 节）。
    """
    if not get_knowledge_config().enabled:
        return {"enabled": False, "docs": 0, "chunks": 0}
    status = _service.status()
    if status.get("error"):
        raise KnowledgeError(f"知识库不可用：{status['error']}")
    _service.ensure_index()
    return {"enabled": True, "docs": status["docs"], "chunks": status["chunks"]}


provide("knowledge.start", _start)

__all__ = [
    "KnowledgeConfig",
    "KnowledgeError",
    "KnowledgeService",
    "get_knowledge_config",
    "get_service",
]
