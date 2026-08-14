"""统一日志配置（loguru）。

输出到控制台（stderr）与日志文件，文件按「天 + 大小」双重轮转：
- 目录结构：`<data_dir>/logs/YYYY-MM-DD/aris.log`，跨天自动建新文件夹
- 文件达到大小上限（默认 10 MB）自动切新文件（aris.log.1、aris.log.2 ...）

控制台日志级别可与文件日志分离：默认控制台只显示 WARNING 及以上（安静），
调试时可通过 CLI `--verbose` 把控制台级别提上来。
"""

import sys
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from .cfgtoml import load_config

_CONSOLE_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan> | <level>{message}</level>"
)
_FILE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan> | <level>{message}</level>"
)


@dataclass
class LoggingConfig:
    """文件日志可调参数（config/logging.toml）。"""

    file_rotation: str = "10 MB"
    retention: str = "30 days"


_logging_config = load_config(LoggingConfig(), "logging.toml")


def setup_logging(
    level: str = "INFO",
    data_dir: Path | None = None,
    *,
    console: bool = True,
    console_level: str | None = None,
) -> None:
    """配置全局日志：控制台（可选）+ 按天/大小轮转的文件日志。

    参数:
        level: 文件日志级别（DEBUG / INFO / WARNING / ERROR），大小写不敏感。
        data_dir: 数据根目录，日志文件写入 `<data_dir>/logs/YYYY-MM-DD/`；
            为 None 时取全局配置 settings.data_dir。
        console: 是否向控制台（stderr）输出日志。全屏 TUI 等「外部直接写终端
            会破坏渲染」的场景应传 False；日志仍写入文件，不会丢失。
        console_level: 控制台日志级别；为 None 时默认显示 WARNING 及以上。
    """
    if data_dir is None:
        from .config import get_settings

        data_dir = get_settings().data_dir
    level = level.upper()
    console_level = (console_level or "WARNING").upper()
    logger.remove()

    if console:
        logger.add(sys.stderr, level=console_level, format=_CONSOLE_FORMAT)

    # 按天建文件夹 + 按大小轮转：{time:YYYY-MM-DD} 在跨天时自动切新目录
    logger.add(
        data_dir / "logs" / "{time:YYYY-MM-DD}" / "aris.log",
        level=level,
        format=_FILE_FORMAT,
        rotation=_logging_config.file_rotation,
        retention=_logging_config.retention,
        encoding="utf-8",
        enqueue=True,  # 线程安全，异步写文件
        backtrace=True,  # 记录异常完整堆栈
        diagnose=True,  # 记录异常变量值，便于调试
    )
