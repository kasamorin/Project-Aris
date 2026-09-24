"""serve 模块测试：步骤选择、失败分级、dry-run、端口探测。

不跑真实启动（PG 自启 / 模型预热 / WebUI 都太重）：编排逻辑用假步骤验证，
真实步骤表只做结构断言。
"""

from __future__ import annotations

import socket
from collections.abc import Callable

import pytest

from aris.serve import run_plan, select_steps
from aris.serve.conf import ServeConfig
from aris.serve.steps import ServeStep, build_steps


def _step(
    name: str,
    *,
    level: str = "optional",
    start: Callable[[], str] | None = None,
    probe: Callable[[], str] | None = None,
    needs: tuple[str, ...] = (),
    blocks: bool = False,
) -> ServeStep:
    """造一个假步骤（探针默认直接通过）。"""
    return ServeStep(
        name=name,
        label=name,
        probe=probe or (lambda: f"{name} 探针通过"),
        level=level,
        start=start,
        needs=needs,
        blocks=blocks,
    )


def _recorder(calls: list[str], tag: str) -> Callable[[], str]:
    """返回一个记录调用并成功的动作。"""

    def _action() -> str:
        calls.append(tag)
        return f"{tag} ok"

    return _action


def test_select_only_expands_dependencies() -> None:
    """--only 会自动补齐被依赖的步骤（否则 knowledge 起不来）。"""
    steps = [_step("a"), _step("b", needs=("a",)), _step("c")]
    assert [s.name for s in select_steps(steps, ["b"], None)] == ["a", "b"]


def test_select_skip_and_unknown_name() -> None:
    steps = [_step("a"), _step("b"), _step("c")]
    assert [s.name for s in select_steps(steps, None, ["c"])] == ["a", "b"]
    with pytest.raises(ValueError):
        select_steps(steps, ["nope"], None)


def test_dry_run_only_probes() -> None:
    """dry-run 只跑探针，绝不执行启动动作。"""
    calls: list[str] = []
    steps = [
        _step("a", probe=_recorder(calls, "probe:a"), start=_recorder(calls, "start:a")),
        _step("b", probe=_recorder(calls, "probe:b"), start=_recorder(calls, "start:b")),
    ]
    outcomes, deferred = run_plan(steps, dry_run=True)
    assert calls == ["probe:a", "probe:b"]
    assert [o.status for o in outcomes] == ["ok", "ok"]
    assert deferred == []


def test_optional_failure_continues() -> None:
    """optional 步骤失败只影响自己，后续步骤照常启动。"""

    def boom() -> str:
        raise RuntimeError("炸了")

    calls: list[str] = []
    steps = [_step("a", start=boom), _step("b", start=_recorder(calls, "b"))]
    outcomes, _ = run_plan(steps)
    assert [o.status for o in outcomes] == ["failed", "ok"]
    assert calls == ["b"]


def test_required_failure_skips_dependents() -> None:
    """required 步骤失败后，依赖它的步骤跳过，其余照常（serve 不整体退出）。"""

    def boom() -> str:
        raise RuntimeError("PG 起不来")

    calls: list[str] = []
    steps = [
        _step("db", level="required", start=boom),
        _step("kb", needs=("db",), start=_recorder(calls, "kb")),
        _step("web", start=_recorder(calls, "web")),
    ]
    outcomes, _ = run_plan(steps)
    assert [o.status for o in outcomes] == ["failed", "skipped", "ok"]
    assert calls == ["web"]


def test_skipped_dependency_skips_dependent() -> None:
    """依赖的步骤没在计划里（被 --skip 掉）时，依赖方跳过而不是硬跑成失败。"""
    calls: list[str] = []
    steps = [
        _step("db"),
        _step("kb", needs=("db",), start=_recorder(calls, "kb")),
    ]
    plan = select_steps(steps, None, ["db"])
    outcomes, _ = run_plan(plan)
    assert [o.status for o in outcomes] == ["skipped"]
    assert calls == []


def test_blocking_step_is_deferred() -> None:
    """阻塞步骤（WebUI）不当场执行，交给编排方打完清单后拉起。"""
    calls: list[str] = []
    steps = [
        _step("a", start=_recorder(calls, "a")),
        _step("web", start=_recorder(calls, "web"), blocks=True),
    ]
    outcomes, deferred = run_plan(steps)
    assert calls == ["a"]
    assert [s.name for s in deferred] == ["web"]
    assert [o.status for o in outcomes] == ["ok", "ok"]


def test_builtin_steps_shape() -> None:
    """真实步骤表的顺序、档位、阻塞标记与预热开关行为。"""
    steps = build_steps(ServeConfig())
    names = [s.name for s in steps]
    assert names == [
        "services",
        "core",
        "persona",
        "behavior",
        "store.db",
        "store.embed",
        "knowledge",
        "webui",
    ]
    levels = {s.name: s.level for s in steps}
    # required 只有「服务表自检」与「数据库」两项
    assert {n for n, level in levels.items() if level == "required"} == {"services", "store.db"}
    assert [s.name for s in steps if s.blocks] == ["webui"]
    assert {s.name: s.needs for s in steps}["knowledge"] == ("store.db",)

    # 关掉预热时，store.embed 退化为「只探针、无启动动作」
    no_preload = {s.name: s for s in build_steps(ServeConfig(preload_embedding=False))}
    assert no_preload["store.embed"].start is None


def test_probe_db_allows_auto_init(monkeypatch) -> None:
    """便携实例不存在时：允许自动获取 → 提示将自动获取；禁止 → 直接报错。

    这是「clone 下来一条命令起服务」的核心行为（`config/serve.toml: init_db`）。
    """
    import aris.serve.steps as steps

    monkeypatch.setattr(
        steps,
        "call",
        lambda *a, **k: {"installed": False, "running": False, "port": 55432},
    )
    assert "自动获取" in steps._probe_db(True)
    with pytest.raises(RuntimeError):
        steps._probe_db(False)


def test_port_in_use() -> None:
    """端口探测：被占用为 True，释放后为 False。"""
    from aris.webui import port_in_use

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = int(sock.getsockname()[1])
        assert port_in_use("127.0.0.1", port) is True
    assert port_in_use("127.0.0.1", port) is False
