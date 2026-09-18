"""store 模块的可调参数（优先级：代码内默认值 < `config/store.toml`）。

遵循配置体系收口原则（见 developDoc/CONFIG.md）：只放**真正可调**的参数，
provider 之类的逻辑类型留在代码里；密钥一律走 `.env`。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from ..cfgtoml import load_config


@dataclass
class StoreConfig:
    """store 模块配置。"""

    # embedding 提供方（当前支持 "local" = 本地 Bekko a25m，384 维）
    embedding_provider: str = "local"
    # 本地模型：HF 仓库 id，或 data/models/ 下的目录名
    local_model: str = "hotchpotch/bekko-embedding-v1-a25m"
    # 本地推理一次喂多少条
    batch_size: int = 16
    # Matryoshka 截断维度（None = 用模型原生维度 384）
    truncate_dim: int | None = None


@lru_cache
def get_store_config() -> StoreConfig:
    """加载 store 配置单例。"""
    return load_config(StoreConfig(), "store.toml")
