"""CLI 入口（argparse 子命令式）。

现有子命令：
- doctor：环境自检（Python 版本、C 扩展、.env）
- llm test：手动验证 LLM 连接（流式对话，用于调试 fallback）
- chat：文字对话（交互循环或单次问答，基于 core/llm）
后续按阶段新增：voice 等。
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
    from aris.core import call
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
    for delta in call("llm.stream", request):
        print(delta, end="", flush=True)
    print()
    return 0


def _cmd_chat(args: argparse.Namespace) -> int:
    """文字对话：有消息参数走单次问答，无参数进入交互循环。"""
    from aris.chat import ARIS_SYSTEM_PROMPT, ChatSession
    from aris.core.llm import LLMEngine, load_providers

    settings = get_settings()
    providers = load_providers(settings.llm_providers_file)
    engine = LLMEngine(
        providers,
        timeout=settings.llm_fallback_timeout,
        error_message=settings.llm_error_message,
    )
    session = ChatSession(
        engine,
        model_id=args.model,
        system_prompt=args.system or ARIS_SYSTEM_PROMPT,
        data_dir=settings.data_dir,
        thinking=args.thinking,
        tools_enabled=not args.no_tools,
    )
    if args.message:
        print("Aris: ", end="", flush=True)
        for delta in session.ask(args.message):
            print(delta, end="", flush=True)
        print()
        return 0
    return session.repl()


def main(argv: list[str] | None = None) -> int:
    """CLI 主入口。"""
    parser = argparse.ArgumentParser(
        prog="aris", description="拟人 AI Aris —— 社会学意义上的人"
    )
    parser.add_argument(
        "--version", action="version", version=f"Aris {__version__}"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="在控制台显示 INFO 级别日志（默认只显示 WARNING 及以上，日志全量写文件）",
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

    p_chat = sub.add_parser("chat", help="文字对话（交互循环或单次问答）")
    p_chat.add_argument(
        "message", nargs="?", help="要发送的消息；不提供则进入交互对话循环"
    )
    p_chat.add_argument(
        "--model",
        default="deepseek-v4-flash-free",
        help="统一模型 id（默认 deepseek-v4-flash-free）",
    )
    p_chat.add_argument(
        "--system",
        default=None,
        help="自定义系统提示词（默认使用内置 Aris 人设）",
    )
    p_chat.add_argument(
        "--thinking",
        action="store_true",
        help="开启思考模式（默认关闭，关闭时首字响应更快）",
    )
    p_chat.add_argument(
        "--no-tools",
        action="store_true",
        help="禁用工具调用（默认开启内置工具）",
    )
    p_chat.set_defaults(func=_cmd_chat)

    args = parser.parse_args(argv)
    settings = get_settings()
    # doctor 是环境自检命令，始终显示 INFO 级别以便查看检查结果
    console_level = "INFO" if (args.verbose or args.command == "doctor") else None
    setup_logging(settings.log_level, settings.data_dir, console_level=console_level)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "llm" and args.llm_command is None:
        p_llm.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
