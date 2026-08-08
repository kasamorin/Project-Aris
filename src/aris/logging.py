"""统一日志配置（loguru）。"""

import sys

from loguru import logger


def setup_logging(level: str = "INFO") -> None:
    """配置全局日志格式与级别，输出到 stderr。"""
    logger.remove()
    logger.add(
        sys.stderr,
        level=level.upper(),
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
        "<cyan>{name}</cyan> | <level>{message}</level>",
    )
