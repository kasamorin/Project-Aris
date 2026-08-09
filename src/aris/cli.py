"""CLI 入口（argparse 子命令式）。

现有子命令：
- doctor：环境自检（Python 版本、C 扩展、.env）
- llm test：手动验证 LLM 连接（流式对话，用于调试 fallback）
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


def _cmd_llm_test(args: argparse.Namespace) -> int:
    """手动验证 LLM 连接：流式对话一次，展示 fallback / 错误处理。"""
    from aris.core.llm import LLMEngine, load_providers, plain_chat

    settings = get_settings()
    providers = load_providers(settings.llm_providers_file)
    engine = LLMEngine(
        providers,
        timeout=settings.llm_fallback_timeout,
        error_message=settings.llm_error_message,
    )

    request = plain_chat(
        model_id=args.model,
        text=args.message,
        system=args.system,
    )
    print("Aris: ", end="", flush=True)
    for delta in engine.stream(request):
        print(delta, end="", flush=True)
    print()
    return 0


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

    p_llm = sub.add_parser("llm", help="LLM 连接调试")
    p_llm_test = p_llm.add_subparsers(dest="llm_command")
    p_test = p_llm_test.add_parser("test", help="手动验证 LLM 连接（流式）")
    p_test.add_argument(
        "--model", default="deepseek-v4-flash-free", help="统一模型 id（默认 deepseek-v4-flash-free）"
    )
    p_test.add_argument(
        "--message", default="用一句话介绍你自己。", help="要发送的用户消息"
    )
    p_test.add_argument(
        "--system", default="你是 Aris，一个拟人 AI，说话简洁自然。", help="系统提示词"
    )
    p_test.set_defaults(func=_cmd_llm_test)

    args = parser.parse_args(argv)
    settings = get_settings()
    setup_logging(settings.log_level, settings.data_dir)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "llm" and args.llm_command is None:
        p_llm.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
