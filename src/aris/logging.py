"""统一日志配置（loguru）。

输出到控制台（stderr）与日志文件，文件按「天 + 大小」双重轮转：
- 目录结构：`<data_dir>/logs/YYYY-MM-DD/aris.log`，跨天自动建新文件夹
- 文件达到大小上限（默认 10 MB）自动切新文件（aris.log.1、aris.log.2 ...）

控制台日志级别可与文件日志分离：默认控制台只显示 WARNING 及以上（安静），
调试时可通过 CLI `--verbose` 把控制台级别提上来。
"""

import sys
from pathlib import Path

from loguru import logger

_CONSOLE_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan> | <level>{message}</level>"
)
_FILE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan> | <level>{message}</level>"
)

# 单个日志文件大小上限（轮转阈值）
_FILE_ROTATION = "10 MB"


def setup_logging(
    level: str = "INFO",
    data_dir: Path = Path("data"),
    console_level: str | None = None,
) -> None:
    """配置全局日志：控制台 + 按天/大小轮转的文件日志。

    参数:
        level: 文件日志级别（DEBUG / INFO / WARNING / ERROR），大小写不敏感。
        data_dir: 数据根目录，日志文件写入 `<data_dir>/logs/YYYY-MM-DD/`。
        console_level: 控制台日志级别；为 None 时默认显示 WARNING 及以上。
    """
    level = level.upper()
    console_level = (console_level or "WARNING").upper()
    logger.remove()

    logger.add(sys.stderr, level=console_level, format=_CONSOLE_FORMAT)

    # 按天建文件夹 + 按大小轮转：{time:YYYY-MM-DD} 在跨天时自动切新目录
    logger.add(
        data_dir / "logs" / "{time:YYYY-MM-DD}" / "aris.log",
        level=level,
        format=_FILE_FORMAT,
        rotation=_FILE_ROTATION,
        retention="30 days",  # 只保留 30 天内的日志
        encoding="utf-8",
        enqueue=True,  # 线程安全，异步写文件
        backtrace=True,  # 记录异常完整堆栈
        diagnose=True,  # 记录异常变量值，便于调试
    )
