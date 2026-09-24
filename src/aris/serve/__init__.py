"""serve 模块 —— 启动编排（`aris serve`，见 developDoc/SERVE.md）。

定位：**组装根 + 启动编排**，相当于一次 init——按序把各模块拉起来，前台打印启动
清单与日志，`Ctrl-C` 收尾。它只调用各模块自己的启动动作（经 CMCB），**不对外提供
任何查询服务**；**非守护**（不做 daemonize / systemd）；**不含 TUI**（`aris chat`
是纯前端，与 serve 互不干涉）。

用法::

    aris serve                    # 全启：PG 自启 + 迁移、embedding 后台预热、knowledge 建表、WebUI 并入
    aris serve --only knowledge   # 只启知识库（自动补齐依赖的 store.db）
    aris serve --skip webui       # 不启 WebUI
    aris serve --dry-run          # 只跑探针、打印清单，不启动任何东西

失败分级（对齐 AGENTS.md 错误处理）：只有 ``store.db`` 是 required，其余 optional；
降级/跳过/失败**一律记日志并给出可执行提示**，绝不静默降级。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from loguru import logger

from .. import __version__
from ..config import get_settings
from ..core import call, services
from .conf import ServeConfig, get_serve_config
from .steps import ServeStep, build_steps

_STATUS_SYMBOL = {"ok": "✓", "failed": "✗", "skipped": "–"}
_LABEL_WIDTH = 12


@dataclass
class StepOutcome:
    """一步的执行结果。"""

    step: ServeStep
    status: str  # ok / failed / skipped
    detail: str = ""

    @property
    def line(self) -> str:
        """清单里的一行（符号 + 步骤名 + 说明）。"""
        symbol = _STATUS_SYMBOL.get(self.status, "?")
        return f"{symbol} {self.step.label:<{_LABEL_WIDTH}} {self.detail}"


def assemble() -> None:
    """集中 import 各服务所有者模块，触发 provide 注册（唯一的组装根）。

    这里的 import 是**装配动作**（触发自注册），不是跨模块业务调用——对齐
    AGENTS.md「CLI 组装根可保持直接引用」的边界。
    """
    import aris.behavior  # noqa: F401  —— loop.run / tools.execute / skills.*
    import aris.core.llm  # noqa: F401  —— llm.stream / llm.race / llm.deltas
    import aris.knowledge  # noqa: F401  —— knowledge.*
    import aris.persona  # noqa: F401  —— persona.system_prompt
    import aris.store  # noqa: F401  —— store.*
    import aris.webui  # noqa: F401  —— webui.start / webui.probe
    from aris.behavior.skills import manager as _skills  # noqa: F401
    from aris.core.llm import fetch as _fetch  # noqa: F401  —— llm.fetch.* / llm.retired.*
    from aris.core.llm import manage as _manage  # noqa: F401  —— llm.providers.*


def select_steps(
    steps: list[ServeStep],
    only: list[str] | None = None,
    skip: list[str] | None = None,
) -> list[ServeStep]:
    """按 ``--only`` / ``--skip`` 选步骤，并补齐依赖。

    规则：``--only`` 会自动带上被依赖的步骤（``--only knowledge`` 自动补 ``store.db``）；
    ``--skip`` 是**硬性排除**——被跳过的步骤不会因为别人依赖它而被加回来，依赖它的
    步骤在 :func:`run_plan` 里标记 skipped。写了不存在的步骤名直接报错，不猜。
    """
    by_name = {step.name: step for step in steps}
    for raw in list(only or []) + list(skip or []):
        if raw not in by_name:
            raise ValueError(f"未知步骤 {raw!r}；可选：{', '.join(by_name)}")
    excluded = set(skip or [])
    selected = (set(only) if only else set(by_name)) - excluded
    # 依赖闭包：被选中的步骤所需的步骤一并带上（--skip 掉的不补回）
    changed = True
    while changed:
        changed = False
        for name in list(selected):
            for dep in by_name[name].needs:
                if dep not in selected and dep not in excluded:
                    selected.add(dep)
                    changed = True
    return [step for step in steps if step.name in selected]


def run_plan(
    steps: list[ServeStep], *, dry_run: bool = False
) -> tuple[list[StepOutcome], list[ServeStep]]:
    """按序执行非阻塞步骤，返回 ``(结果, 待执行的阻塞步骤)``。

    ``dry_run=True`` 时只跑探针，不执行任何启动动作。``required`` 步骤失败后，
    依赖它的步骤标记为 skipped（其余照常继续——serve 不整体退出）。
    """
    outcomes: list[StepOutcome] = []
    deferred: list[ServeStep] = []
    failed_required: set[str] = set()
    planned = {step.name for step in steps}
    for step in steps:
        blocked_by = [
            dep for dep in step.needs if dep not in planned or dep in failed_required
        ]
        if blocked_by:
            reason = f"依赖的步骤未启用或失败（{', '.join(blocked_by)}），已跳过"
            logger.warning(f"跳过 {step.label}：{reason}")
            outcomes.append(StepOutcome(step, "skipped", reason))
            continue
        if not dry_run and step.blocks:
            deferred.append(step)
            outcomes.append(StepOutcome(step, "ok", "待启动（清单打印后拉起）"))
            continue
        action = step.probe if dry_run else (step.start or step.probe)
        try:
            detail = action() or ""
        except Exception as exc:
            logger.error(f"{step.label} 启动失败：{exc}")
            outcomes.append(StepOutcome(step, "failed", str(exc)))
            if step.level == "required":
                failed_required.add(step.name)
        else:
            outcomes.append(StepOutcome(step, "ok", str(detail)))
    return outcomes, deferred


def _teardown(config: ServeConfig) -> None:
    """退出收尾：只停「本次 serve 自启的」数据库（原本在跑的不动）。"""
    if not config.stop_db_on_exit:
        logger.info("按配置保留数据库运行（stop_db_on_exit = false）")
        return
    try:
        stopped = call("store.stop", only_self_started=True)
    except Exception as exc:
        logger.warning(f"停止数据库失败：{exc}")
        return
    if stopped:
        logger.info("已停止本次自启的数据库（原先就在运行的实例不受影响）")


def _log_outcome(outcome: StepOutcome) -> None:
    """打印一行启动清单（失败/跳过必定有日志，见 SERVE.md 第 5 节）。"""
    if outcome.status == "ok":
        logger.success(outcome.line)
    else:
        logger.warning(outcome.line)


def serve(
    *,
    only: list[str] | None = None,
    skip: list[str] | None = None,
    dry_run: bool = False,
) -> int:
    """`aris serve` 的入口：组装 → 选步骤 → 执行 → 打清单 → 拉起阻塞步骤 → 收尾。

    返回进程退出码：0 正常，1 有 required 步骤失败，2 CLI 参数写错（由调用方给）。
    """
    config = get_serve_config()
    settings = get_settings()

    skipped = list(config.skip) + list(skip or [])
    if not config.web_enabled and not (only and "webui" in only):
        skipped.append("webui")  # 配置里关了 WebUI；显式 --only webui 时以用户为准

    assemble()
    plan = select_steps(build_steps(config), only, skipped)

    logger.info(
        f"aris serve v{__version__}  data={settings.data_dir}  pid={os.getpid()}"
        + ("  [dry-run]" if dry_run else "")
    )
    outcomes, deferred = run_plan(plan, dry_run=dry_run)
    for outcome in outcomes:
        _log_outcome(outcome)

    failed_required = [
        outcome
        for outcome in outcomes
        if outcome.status == "failed" and outcome.step.level == "required"
    ]
    if dry_run:
        passed = sum(outcome.status == "ok" for outcome in outcomes)
        failed = sum(outcome.status == "failed" for outcome in outcomes)
        logger.info(f"dry-run 结束：探针通过 {passed} 项、失败 {failed} 项；未启动任何东西")
        return 1 if failed_required else 0

    logger.info(f"总线服务已注册 {len(services())} 个 · Ctrl-C 停止")
    exit_code = 1 if failed_required else 0
    if not deferred:
        # 没有常驻步骤（webui 未启用 / 被 --skip）时不该"起了又立刻停"——那等于白折腾
        # 一遍，也让 `aris serve --only store.db` 这种用法彻底没用
        logger.warning(
            "没有常驻步骤（webui 未启用或被跳过）：不执行收尾，数据库保持运行"
            "（需要停止用 `aris db stop`）"
        )
        return exit_code
    try:
        for step in deferred:
            logger.info(f"拉起 {step.label}（阻塞，Ctrl-C 停止）...")
            if step.start is not None:
                step.start()
    except KeyboardInterrupt:
        logger.info("收到中断，正在收尾 ...")
    except Exception as exc:  # 阻塞步骤启动失败（如端口被占）不拖垮收尾
        logger.error(f"{deferred[0].label if deferred else 'serve'} 启动失败：{exc}")
        exit_code = 1
    finally:
        _teardown(config)
    return exit_code


__all__ = ["StepOutcome", "assemble", "run_plan", "select_steps", "serve"]
