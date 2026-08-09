"""CLI 入口（argparse 子命令式）。

现有子命令：
- doctor：环境自检（Python 版本、C 扩展、.env）
后续按阶段新增：chat / voice 等。
"""

import argparse
import sys
from pathlib import Path

from loguru import logger

from . import __version__
from .config import get_settings
from .logging import setup_logging


def _cmd_doctor(args: argparse.Namespace) -> int:
    """环境自检：Python 版本、C 扩展可用性、.env 是否存在。"""
    ok = True

    logger.info(f"Aris {__version__}")
    logger.info(f"Python: {sys.version.split()[0]} (需要 >= 3.12)")
    if sys.version_info < (3, 12):
        logger.error("Python 版本过低，无法运行")
        ok = False

    try:
        from aris.csrc import demo_available

        if demo_available():
            logger.info("C 扩展: 已加载（demo.so 可用）")
        else:
            logger.warning("C 扩展: 未加载（未编译 demo.so，主功能不受影响）")
    except ImportError as e:  # 防御：csrc 模块本身异常时降级
        logger.warning(f"C 扩展: 模块异常（{e}），已降级")

    if Path(".env").exists():
        logger.info(".env: 存在")
    else:
        logger.info(".env: 不存在（可复制 .env.example，非必需）")

    settings = get_settings()
    logger.info(f"数据目录: {settings.data_dir}")

    if ok:
        logger.success("环境自检通过")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    """CLI 主入口。"""
    parser = argparse.ArgumentParser(
        prog="aris", description="拟人 AI Aris —— 社会学意义上的人"
    )
    parser.add_argument(
        "--version", action="version", version=f"Aris {__version__}"
    )
    sub = parser.add_subparsers(dest="command")

    p_doctor = sub.add_parser("doctor", help="环境自检")
    p_doctor.set_defaults(func=_cmd_doctor)

    args = parser.parse_args(argv)
    settings = get_settings()
    setup_logging(settings.log_level, settings.data_dir)

    if args.command is None:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
