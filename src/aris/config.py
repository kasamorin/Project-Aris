"""全局配置。

通过 pydantic-settings 从环境变量与 .env 文件读取，所有字段带 ARIS_ 前缀。
后续各模块的配置（LLM key、Embedding 等）按需往这里追加。
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例。"""
    return Settings()
