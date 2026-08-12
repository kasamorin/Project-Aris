"""模块级配置文件加载：`config/` 目录下的 toml。

各功能模块的可调参数（超时、轮数、日志轮转等）收口到模块级 toml，
遵循优先级：**代码内 dataclass 默认值 < config/*.toml**（缺文件/缺键用默认）。

边界（三个配置源各管一摊，勿混淆）：
- `.env`（ARIS_ 前缀，pydantic-settings）：启动级参数、密钥、data_dir 等
- `config/providers.toml`：LLM 提供方（base_url / key 环境变量名 / 模型）
- `config/*.toml`：功能可调参数（本模块）
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path

from loguru import logger

# config/ 目录绝对路径（相对本文件向上 2 级 = 项目根），与运行 cwd 无关
CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def config_dir() -> Path:
    """返回配置目录路径。"""
    return CONFIG_DIR


def load_config(instance: dataclass, filename: str) -> dataclass:
    """把 `config/<filename>` 中与 dataclass 字段同名的键覆盖到实例。

    文件缺失、解析失败或键不存在时静默用默认值，不抛异常
    （配置缺失不致命，代码内默认值兜底）。
    """
    path = CONFIG_DIR / filename
    if not path.exists():
        return instance
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        logger.warning(f"配置文件 {path} 解析失败，使用默认值: {e}")
        return instance
    if not is_dataclass(instance):
        raise TypeError(f"load_config 需要 dataclass 实例，得到 {type(instance)!r}")
    for field in fields(instance):
        if field.name in data:
            setattr(instance, field.name, data[field.name])
    return instance
