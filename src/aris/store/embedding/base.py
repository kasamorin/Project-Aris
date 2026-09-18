"""embedding 提供方协议（文本 → 向量）。

只做一件事：把文本编码成**固定维度**的向量。**检索由 PostgreSQL + pgvector 执行**，
与提供方无关（见 developDoc/EMBEDDING.md 第 0 节）。因此：

- 维度是提供方的固有属性，业务侧据此选表；
- 不同 provider 维度不同（384 / 1024）→ 一个表只能有一种维度，各建各表。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class EmbeddingError(RuntimeError):
    """embedding 不可用或编码失败（依赖缺失 / 模型加载失败 / 配置有误）。"""


@runtime_checkable
class EmbeddingProvider(Protocol):
    """文本 → 向量（顺序与入参一致，维度固定）。"""

    @property
    def name(self) -> str:
        """提供方标识（如 ``local:bekko-a25m``）。"""

    @property
    def dimension(self) -> int:
        """向量维度（384 / 1024 ...）。"""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量编码文本；返回顺序与入参一致。"""
