"""embedding 抽象：提供方注册与取用。

- 协议：`base.EmbeddingProvider`（文本 → 向量，维度由 provider 决定）
- 本地实现：`local.LocalBekkoProvider`（Bekko a25m，懒加载 + 重依赖可选安装）
- 对外总线服务：``store.embed``（入参文本列表，返回向量列表）

按 C1 定案（developDoc/KNOWLEDGE-BASE.md 5.2），知识库只用**本地 384 维**；
云端 BGE-M3 属 `memory/` 冷侧，将来需要时在本模块加 provider 即可，
调用方（业务模块）不用改。
"""

from __future__ import annotations

from .base import EmbeddingError, EmbeddingProvider
from ..conf import get_store_config

# provider 单例：本地模型常驻内存，避免重复加载（加载一次约 20s / 1.5 GiB）
_providers: dict[str, EmbeddingProvider] = {}


def create_provider(name: str | None = None) -> EmbeddingProvider:
    """按名字新建提供方实例（当前仅支持 ``local``）。"""
    cfg = get_store_config()
    key = (name or cfg.embedding_provider).lower()
    if key == "local":
        from .local import provider_from_config

        return provider_from_config()
    raise EmbeddingError(f"未知的 embedding provider: {key}（当前支持 local）")


def get_provider(name: str | None = None) -> EmbeddingProvider:
    """取提供方单例（同名复用）。"""
    key = (name or get_store_config().embedding_provider).lower()
    if key not in _providers:
        _providers[key] = create_provider(key)
    return _providers[key]


def embed(texts: list[str], provider: str | None = None) -> list[list[float]]:
    """编码文本（总线服务 ``store.embed`` 的实现）。"""
    return get_provider(provider).embed(texts)


__all__ = [
    "EmbeddingError",
    "EmbeddingProvider",
    "create_provider",
    "embed",
    "get_provider",
]
