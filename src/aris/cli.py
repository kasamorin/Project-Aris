"""CLI 入口（argparse 子命令式）。

现有子命令：
- doctor：环境自检（Python 版本、C 扩展、.env）
- llm test：手动验证 LLM 连接（流式对话，用于调试 fallback）
- chat：文字对话（交互循环或单次问答，基于 core/llm）
后续按阶段新增：voice 等。
"""

import argparse
import os
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

    # LLM 配置体检摘要（不影响 doctor 整体退出码，详情见 aris llm check）
    try:
        from aris.core.llm import load_providers
        from aris.core.llm.config import ProviderConfigError

        providers = load_providers(settings.llm_providers_file)
    except ProviderConfigError as e:
        logger.error(f"LLM 配置: {e}")
    else:
        issues = _collect_check_issues(providers)
        if issues:
            err_count = sum(1 for level, _ in issues if level == "error")
            logger.warning(
                f"LLM 配置: {len(issues)} 个问题（{err_count} 个错误），运行 aris llm check 查看详情"
            )
        else:
            logger.success("LLM 配置: 通过")

    if ok:
        logger.success("环境自检通过")
    return 0 if ok else 1


def _provider_key_status(provider) -> str:
    """提供方密钥状态文本：[就位] / [缺 key]。"""
    if os.environ.get(provider.api_key_env):
        return f"{provider.api_key_env} [就位]"
    return f"{provider.api_key_env} [缺 key]"


def _format_context(n: int | None) -> str:
    """把 tokens 数格式化为可读文本（200K / 1M / -）。"""
    if not n:
        return "-"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.0f}M"
    if n >= 1000:
        return f"{n // 1000}K"
    return str(n)


def _cmd_llm_list(args: argparse.Namespace) -> int:
    """列出全部提供方 + 模型 + 密钥状态 + 元数据，默认模型标 [默认]。"""
    from aris.core.llm import load_providers
    from aris.core.llm.config import ProviderConfigError

    settings = get_settings()
    try:
        providers = load_providers(settings.llm_providers_file)
    except ProviderConfigError as e:
        logger.error(str(e))
        return 1
    default_model = providers.resolve_default_model()

    for provider in providers.ordered_providers():
        print(f"提供方: {provider.id} ({provider.name})")
        print(f"  地址: {provider.base_url}")
        print(f"  传输: {provider.transport} | 密钥: {_provider_key_status(provider)}")
        if not provider.models:
            print("  模型: （空）")
            continue
        print("  模型:")
        for m in provider.models:
            marker = "  [默认]" if m.id == default_model else ""
            caps = ", ".join(m.capabilities) if m.capabilities else "-"
            name_col = f"{m.id}{marker}".ljust(34)
            print(
                f"    - {name_col}  capabilities: {caps:<20}  context: {_format_context(m.context_length)}"
            )
    print(f"\n默认模型: {default_model}")
    return 0


def _collect_check_issues(providers) -> list[tuple[str, str]]:
    """收集配置体检问题：[(level, message)]，level ∈ error / warning。"""
    issues: list[tuple[str, str]] = []
    known = {p.id for p in providers.providers}
    for pid in providers.order:
        if pid not in known:
            issues.append(("error", f"default_provider_order 引用不存在的提供方: {pid}"))
    for p in providers.providers:
        if not p.models:
            issues.append(("error", f"提供方 {p.id} 模型列表为空"))
        if not os.environ.get(p.api_key_env):
            issues.append(("error", f"提供方 {p.id} 缺 API key：请在 .env 设置 {p.api_key_env}"))
    if not providers.default_model:
        issues.append(("warning", "default_model 未配置，CLI 将自动兜底取第一个可用模型"))
    elif providers.default_model not in providers.all_model_ids():
        issues.append(
            ("warning", f"default_model {providers.default_model} 不存在于任何提供方，将自动兜底")
        )
    return issues


def _cmd_llm_check(args: argparse.Namespace) -> int:
    """配置体检：重复 id / order 引用 / 缺 key / 默认模型，有问题非零退出。"""
    from aris.core.llm import load_providers
    from aris.core.llm.config import ProviderConfigError

    settings = get_settings()
    try:
        providers = load_providers(settings.llm_providers_file)
    except ProviderConfigError as e:
        logger.error(str(e))
        return 1
    issues = _collect_check_issues(providers)
    if not issues:
        logger.success("LLM 配置体检通过")
        return 0
    for level, message in issues:
        (logger.error if level == "error" else logger.warning)(f"[{level}] {message}")
    err_count = sum(1 for level, _ in issues if level == "error")
    return 1 if err_count else 0


def _cmd_llm_test(args: argparse.Namespace) -> int:
    """手动验证 LLM 连接：流式对话一次，展示 fallback / 错误处理。"""
    from aris.core import call
    from aris.core.llm import LLMEngine, load_providers, plain_chat

    settings = get_settings()
    providers = load_providers(settings.llm_providers_file)
    engine = LLMEngine(
        providers,
        timeout=settings.llm_fallback_timeout,
        first_token_stall=settings.llm_first_token_stall,
        error_message=settings.llm_error_message,
    )

    model_id = args.model or providers.resolve_default_model()
    request = plain_chat(
        model_id=model_id,
        text=args.message,
        system=args.system,
    )
    print("Aris: ", end="", flush=True)
    for delta in call("llm.stream", request):
        print(delta, end="", flush=True)
    print()
    return 0


# ---------------------------------------------------------------------------
# aris llm fetch / aris llm retired
# ---------------------------------------------------------------------------


def _series_prefix(model_id: str) -> str:
    """模型系列前缀：取 id 第一个 - 前段（如 claude-3 → claude）。"""
    return model_id.split("-", 1)[0] if "-" in model_id else model_id


def _pick_fetch_provider(providers, provider_id: str | None):
    """选择 fetch 目标提供方：显式指定 / default_model 所在 / order 第一个。"""
    if provider_id:
        for p in providers.providers:
            if p.id == provider_id:
                return p
        logger.error(f"提供方不存在: {provider_id}")
        return None
    default = providers.resolve_default_model()
    if default:
        for p in providers.providers:
            if p.get_model(default):
                return p
    return providers.ordered_providers()[0]


def _run_candidate_picker(
    title: str, candidates: list[LLMModel]
) -> set[str] | None:
    """按系列分组分页的勾选列表（prompt_toolkit）。

    按键：↑/↓ 或 j/k 移动，空格 勾选/取消，p/n 翻页，回车 确认，q/ESC 放弃。
    返回勾选的模型 id 集合；放弃返回 None。
    """
    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.layout import Layout

    groups: dict[str, list[LLMModel]] = {}
    for c in candidates:
        groups.setdefault(_series_prefix(c.id), []).append(c)
    pages = [sorted(v, key=lambda m: m.id) for _, v in sorted(groups.items())]
    selected: set[str] = set()
    page, row = 0, 0
    result: set[str] | None = None

    def meta_line(m: LLMModel) -> str:
        ctx = f"{m.context_length // 1000}K" if m.context_length else "-"
        caps = ",".join(m.capabilities) if m.capabilities else "-"
        return f"{m.name}  [ctx {ctx}]  [{caps}]"

    def build_text() -> str:
        items = pages[page]
        lines = [
            f"# {title}",
            f"  页面 {page + 1}/{len(pages)}，系列 {_series_prefix(items[0].id)}，"
            f"已选 {len(selected)} 个",
            "",
        ]
        for i, m in enumerate(items):
            mark = "[x]" if m.id in selected else "[ ]"
            cursor = ">" if i == row else " "
            lines.append(f" {cursor}{mark} {m.id:<28} {meta_line(m)}")
        lines += [
            "",
            " ↑/↓ 或 j/k 移动   空格 勾选/取消   p/n 翻页   回车 确认   q/ESC 放弃",
        ]
        return "\n".join(lines)

    text_control = FormattedTextControl(HTML)

    def set_content() -> None:
        text_control.text = build_text()

    kb = KeyBindings()

    @kb.add("up", "k")
    def _(event):
        nonlocal row
        row = (row - 1) % len(pages[page])
        set_content()

    @kb.add("down", "j")
    def _(event):
        nonlocal row
        row = (row + 1) % len(pages[page])
        set_content()

    @kb.add(" ")
    def _(event):
        mid = pages[page][row].id
        selected.symmetric_difference_update({mid})
        set_content()

    @kb.add("p")
    def _(event):
        nonlocal page, row
        page = (page - 1) % len(pages)
        row = 0
        set_content()

    @kb.add("n")
    def _(event):
        nonlocal page, row
        page = (page + 1) % len(pages)
        row = 0
        set_content()

    @kb.add("enter")
    def _(event):
        nonlocal result
        result = selected
        event.app.exit()

    @kb.add("q", "c-q", "escape")
    def _(event):
        event.app.exit()

    set_content()
    app = Application(
        layout=Layout(HSplit([Window(text_control)])),
        key_bindings=kb,
        full_screen=True,
    )
    app.run()
    return result


def _cmd_llm_fetch(args: argparse.Namespace) -> int:
    """/models 同步：拉取 → 对比 → 勾选/对齐 → 退休巡检 → 写回。

    默认 dry-run（只打印 diff 不落盘）；--write 才应用变更。
    """
    from aris.core.llm import load_providers
    from aris.core.llm.config import ProviderConfigError
    from aris.core.llm.errors import AuthError, LLMError
    from aris.core.llm.fetch import (
        apply_sync,
        fetch_provider_models,
        load_retired,
        modelsdev_load,
        plan_sync,
        retired_file_path,
    )

    settings = get_settings()
    try:
        providers = load_providers(settings.llm_providers_file)
    except ProviderConfigError as e:
        logger.error(str(e))
        return 1

    provider = _pick_fetch_provider(providers, args.provider_id)
    if provider is None:
        return 1

    print(f"拉取 {provider.id} /models ...", flush=True)
    try:
        endpoint_ids = fetch_provider_models(provider)
    except (LLMError, AuthError) as e:
        logger.error(str(e))
        return 1
    print(f"  端点共 {len(endpoint_ids)} 个模型")

    modelsdev = modelsdev_load(settings.data_dir, refresh=args.refresh)
    retired = load_retired()
    plan = plan_sync(provider, endpoint_ids, retired, modelsdev)

    # ---- 打印 diff ----
    d, r = plan.diff, plan.retire
    print(f"\n对比 {provider.id}（本地 {len(provider.models)} 个）:")
    print(f"  云有本地无（添加候选）: {len(d.added)} 个")
    for mid in d.added:
        print(f"    + {mid}")
    print(f"  两边都有（保留）: {len(d.kept)} 个")
    if d.missing:
        print(f"  本地有云无（→退休）: {len(d.missing)} 个")
        for mid in d.missing:
            print(f"    - {mid}")
    if r.restored:
        print(f"  退休回归（自动恢复）: {r.restored}")
    if r.expired:
        print(f"  退休超期（永久删除）: {[e.model for e in r.expired]}")
    if r.retired_now:
        print(f"  新退休（进入宽限期）: {[e.model for e in r.retired_now]}")

    if not args.write:
        print("\n（dry-run，未写入任何文件；确认后加 --write 应用变更）")
        return 0

    # ---- 选择要添加的候选 ----
    selected: set[str] | None
    if args.add:
        wanted = set(args.add.split(","))
        selected = {c.id for c in plan.candidates if c.id in wanted}
        missing_wanted = wanted - {c.id for c in plan.candidates}
        if missing_wanted:
            logger.warning(f"--add 中不在端点/候选的模型: {sorted(missing_wanted)}")
    elif sys.stdin.isatty() and plan.candidates:
        picked = _run_candidate_picker(
            f"选择要添加的模型（{provider.id}）", plan.candidates
        )
        if picked is None:
            print("已放弃，未写入。")
            return 0
        selected = picked
    else:
        selected = {c.id for c in plan.candidates}

    if args.delete:
        selected -= set(args.delete.split(","))

    keep = set(args.keep.split(",")) if args.keep else set()

    # ---- 应用 ----
    apply_sync(
        plan,
        sorted(selected),
        cfg=providers,
        providers_path=settings.llm_providers_file,
        retired=retired,
        keep=sorted(keep),
        retired_path=retired_file_path(),
    )
    print(f"\n已写入 {settings.llm_providers_file}")
    print(f"  新增: {sorted(selected)}")
    print(f"  移除(退休): {sorted(set(d.missing) - keep)}")
    print(f"  保留(keep): {sorted(keep)}")
    print(f"  备份: {settings.llm_providers_file}.bak")
    return 0


def _cmd_llm_retired(args: argparse.Namespace) -> int:
    """退休模型管理：列出 + 手动删除（交互勾选或 --delete 指定）。"""
    from aris.core.llm.fetch import load_retired, save_retired

    entries = load_retired()
    if not entries:
        print("退休列表为空。")
        return 0

    print(f"退休模型共 {len(entries)} 个：")
    for e in entries:
        print(f"  [{e.provider}] {e.model}  (自 {e.first_missing})")

    if args.delete:
        wanted = set(args.delete.split(","))
        kept = [e for e in entries if e.model not in wanted]
        save_retired(kept)
        print(f"已删除退休记录: {sorted(wanted)}")
        return 0

    if not sys.stdin.isatty():
        print("\n（非终端；可用 --delete id,... 删除）")
        return 0

    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.layout import Layout

    row = 0
    selected: set[int] = set()
    confirmed = False

    def build_text() -> str:
        lines = ["# 选择要永久删除的退休模型（回车确认删除）", ""]
        for i, e in enumerate(entries):
            mark = "[x]" if i in selected else "[ ]"
            cursor = ">" if i == row else " "
            lines.append(f" {cursor}{mark} {e.model:<30} 自 {e.first_missing}")
        lines += ["", " ↑/↓ 或 j/k 移动   空格 选择   回车 确认删除   q/ESC 放弃"]
        return "\n".join(lines)

    text_control = FormattedTextControl(HTML)
    text_control.text = build_text()

    def set_content() -> None:
        text_control.text = build_text()

    kb = KeyBindings()

    @kb.add("up", "k")
    def _(event):
        nonlocal row
        row = (row - 1) % len(entries)
        set_content()

    @kb.add("down", "j")
    def _(event):
        nonlocal row
        row = (row + 1) % len(entries)
        set_content()

    @kb.add(" ")
    def _(event):
        selected.symmetric_difference_update({row})
        set_content()

    @kb.add("enter")
    def _(event):
        nonlocal confirmed
        confirmed = True
        event.app.exit()

    @kb.add("q", "c-q", "escape")
    def _(event):
        event.app.exit()

    Application(
        layout=Layout(HSplit([Window(text_control)])),
        key_bindings=kb,
        full_screen=True,
    ).run()

    if confirmed and selected:
        targets = {entries[i].model for i in selected}
        kept = [e for e in entries if e.model not in targets]
        save_retired(kept)
        print(f"已删除退休记录: {sorted(targets)}")
    return 0


def _cmd_chat(args: argparse.Namespace) -> int:
    """文字对话：有消息参数走单次问答，无参数进入交互循环。"""
    from aris.chat import ChatSession
    from aris.core.llm import LLMEngine, load_providers

    settings = get_settings()
    providers = load_providers(settings.llm_providers_file)
    engine = LLMEngine(
        providers,
        timeout=settings.llm_fallback_timeout,
        first_token_stall=settings.llm_first_token_stall,
        error_message=settings.llm_error_message,
    )
    session = ChatSession(
        engine,
        model_id=args.model or providers.resolve_default_model(),
        system_prompt=args.system,  # None 时使用 persona 人设（提示词工程）
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

    p_llm = sub.add_parser("llm", help="LLM 提供方与模型管理")
    p_llm_test = p_llm.add_subparsers(dest="llm_command")
    p_list = p_llm_test.add_parser("list", help="列出提供方与模型（含密钥状态/元数据）")
    p_list.set_defaults(func=_cmd_llm_list)
    p_check = p_llm_test.add_parser(
        "check", help="配置体检（重复 id / 缺 key / 默认模型），有问题非零退出"
    )
    p_check.set_defaults(func=_cmd_llm_check)
    p_test = p_llm_test.add_parser("test", help="手动验证 LLM 连接（流式）")
    p_test.add_argument(
        "--model",
        default=None,
        help="统一模型 id（默认取 config/providers.toml 的 default_model）",
    )
    p_test.add_argument(
        "--message", default="用一句话介绍你自己。", help="要发送的用户消息"
    )
    p_test.add_argument(
        "--system", default="你是 Aris，一个拟人 AI，说话简洁自然。", help="系统提示词"
    )
    p_test.set_defaults(func=_cmd_llm_test)

    p_fetch = p_llm_test.add_parser(
        "fetch", help="与 /models 端点同步模型列表（对比/勾选/退休巡检）"
    )
    p_fetch.add_argument(
        "provider_id", nargs="?", default=None, help="目标提供方（默认取 default_model 所在）"
    )
    p_fetch.add_argument("--refresh", action="store_true", help="强制刷新 models.dev 缓存")
    p_fetch.add_argument(
        "--write", action="store_true", help="应用变更并写回（默认只打印 diff，不落盘）"
    )
    p_fetch.add_argument(
        "--add", default=None, help="只添加指定模型（逗号分隔，跳过勾选）"
    )
    p_fetch.add_argument(
        "--keep", default=None, help="保留这些模型不移除（逗号分隔，即使云端已消失）"
    )
    p_fetch.add_argument(
        "--delete", default=None, help="从不添加候选的模型中排除（逗号分隔）"
    )
    p_fetch.set_defaults(func=_cmd_llm_fetch)

    p_retired = p_llm_test.add_parser(
        "retired", help="退休模型管理（列出 / 交互删除 / --delete 指定）"
    )
    p_retired.add_argument(
        "--delete", default=None, help="直接删除指定退休模型（逗号分隔，非交互）"
    )
    p_retired.set_defaults(func=_cmd_llm_retired)

    p_chat = sub.add_parser("chat", help="文字对话（交互循环或单次问答）")
    p_chat.add_argument(
        "message", nargs="?", help="要发送的消息；不提供则进入交互对话循环"
    )
    p_chat.add_argument(
        "--model",
        default=None,
        help="统一模型 id（默认取 config/providers.toml 的 default_model）",
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
    # chat 命令默认不向控制台输出日志——全屏 TUI 由 prompt_toolkit 接管终端，
    # loguru 直接写 stderr 会破坏渲染（spinner 残留、界面错位）；日志仍写文件。
    # --verbose 可强制开启，用于联调排查。
    console = not (args.command == "chat" and not args.verbose)
    setup_logging(
        settings.log_level,
        settings.data_dir,
        console=console,
        console_level=console_level,
    )

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "llm" and args.llm_command is None:
        p_llm.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
