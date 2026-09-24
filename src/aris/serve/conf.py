"""serve 模块的可调参数（优先级：代码内默认值 < `config/serve.toml`）。

只放**真正可调**的启动编排开关（见 developDoc/SERVE.md 第 6 节）；具体步骤的
行为归各模块自己，这里不重复配置它们的参数。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from ..cfgtoml import load_config


@dataclass
class ServeConfig:
    """启动编排可调参数。"""

    # 数据库没在跑时是否自启便携实例
    start_db: bool = True
    # 便携实例不存在时是否自动获取（clone 下来一条命令起服务；需联网，首次数分钟）
    init_db: bool = True
    # 退出时是否停掉「本次自启的」数据库（原本就在跑的不动）
    stop_db_on_exit: bool = True
    # 启动时后台预热本地 embedding
    preload_embedding: bool = True
    # 是否把 WebUI 一并拉起（host / port 仍归 config/webui.toml）
    web_enabled: bool = True
    # 默认跳过的步骤名（CLI --skip 追加）
    skip: list[str] = field(default_factory=list)


@lru_cache
def get_serve_config() -> ServeConfig:
    """加载启动编排配置单例。"""
    return load_config(ServeConfig(), "serve.toml")
