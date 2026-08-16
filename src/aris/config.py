"""全局配置。

通过 pydantic-settings 从环境变量与 .env 文件读取，所有字段带 ARIS_ 前缀。
后续各模块的配置（LLM key、Embedding 等）按需往这里追加。

注意：pydantic-settings 读取 .env 后并不会把变量注入 os.environ，
而 LLM 提供方的 api_key_env 是直接读 os.environ 的，因此在构造 Settings
之前先把 .env 解析并 setdefault 进 os.environ，保证两种读取方式一致。
"""

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from .cfgtoml import config_dir


def _load_env_into_environ() -> None:
    """把 .env 中的变量 setdefault 进 os.environ（不覆盖已存在的环境变量）。"""
    env_file = Path(".env")
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


class Settings(BaseSettings):
    """Aris 全局配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ARIS_",
        extra="ignore",
    )

    log_level: str = "INFO"
    data_dir: Path = Path("data")

    # LLM 连接
    llm_providers_file: Path = config_dir() / "providers.toml"
    llm_fallback_timeout: float = 30.0
    llm_first_token_stall: float = 3.0  # 首字占位：超过该秒数无产出先显示预设提示语
    llm_error_message: str = (
        "Someone tell Morin there's some problem with my AI."
    )


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例（首次调用时同步 .env 到 os.environ）。"""
    _load_env_into_environ()
    return Settings()
