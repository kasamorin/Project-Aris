"""统一日志配置（loguru）。

输出到控制台（stderr）与日志文件，文件按日期轮转，统一存
`<data_dir>/logs/`。日志目录自动创建，无需手动管理。
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


def setup_logging(level: str = "INFO", data_dir: Path = Path("data")) -> None:
    """配置全局日志：控制台 + 按日期轮转的文件日志。

    参数:
        level: 日志级别（DEBUG / INFO / WARNING / ERROR），大小写不敏感。
        data_dir: 数据根目录，日志文件写入 `<data_dir>/logs/`。
    """
    level = level.upper()
    logger.remove()

    logger.add(sys.stderr, level=level, format=_CONSOLE_FORMAT)

    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_dir / "aris-{time:YYYY-MM-DD}.log",
        level=level,
        format=_FILE_FORMAT,
        rotation="00:00",  # 按日期轮转（跨天时新建文件）
        retention="30 days",  # 日志文件保留 30 天
        encoding="utf-8",
        enqueue=True,  # 线程安全，异步写文件
        backtrace=True,  # 记录异常完整堆栈
        diagnose=True,  # 记录异常变量值，便于调试
    )
