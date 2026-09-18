"""store 模块测试：环境探针与 embedding 抽象。

刻意保持**无外部依赖**：不连数据库、不加载真实模型（本地 embedding 属可跳过的重依赖组），
只验证探针链、DSN 拼装、provider 注册与错误分支。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aris.core import bus
from aris.store import EmbeddingError, PgSource, detect, get_provider
from aris.store.embedding.local import BEKKO_A25M_DIM, LocalBekkoProvider


@pytest.fixture(autouse=True)
def _clean_pg_env(monkeypatch):
    """清掉可能影响探针链的环境变量，保证用例与宿主环境无关。"""
    for key in ("ARIS_PG_BIN", "ARIS_PG_DSN", "ARIS_PG_PORT", "ARIS_PG_USER", "ARIS_PG_DB"):
        monkeypatch.delenv(key, raising=False)


def _fake_bin(directory: Path) -> Path:
    """造一个「看起来像 PG 安装」的 bin 目录。"""
    bin_dir = directory / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "postgres").write_text("#!/bin/sh\n", encoding="utf-8")
    return bin_dir


def test_detect_env_override(tmp_path, monkeypatch):
    """ARIS_PG_BIN 优先级最高，且路径解析为绝对路径。"""
    bin_dir = _fake_bin(tmp_path / "pg")
    monkeypatch.setenv("ARIS_PG_BIN", str(bin_dir))

    env = detect(tmp_path / "data")

    assert env.source is PgSource.ENV
    assert env.bin_dir == bin_dir
    assert env.installed is True
    assert env.pgdata.is_absolute()


def test_detect_project_fallback(tmp_path, monkeypatch):
    """系统没装时回落到项目内 data/pg。"""
    monkeypatch.setattr("aris.store.pgenv.shutil.which", lambda _name: None)
    _fake_bin(tmp_path / "data" / "pg")

    env = detect(tmp_path / "data")

    assert env.source is PgSource.PROJECT
    assert env.prefix == (tmp_path / "data" / "pg").resolve()


def test_detect_missing(tmp_path, monkeypatch):
    """全无命中时标记未安装，但路径仍然可算出来（供 bootstrap 用）。"""
    monkeypatch.setattr("aris.store.pgenv.shutil.which", lambda _name: None)

    env = detect(tmp_path / "data")

    assert env.source is PgSource.MISSING
    assert env.bin_dir is None
    assert env.installed is False
    with pytest.raises(RuntimeError):
        env.tool("psql")


def test_dsn_and_tool_env(tmp_path, monkeypatch):
    """DSN 默认拼装，ARIS_PG_DSN 可整条覆盖；工具环境变量走 unix socket。"""
    monkeypatch.setattr("aris.store.pgenv.shutil.which", lambda _name: None)
    env = detect(tmp_path / "data")

    assert env.dsn == f"postgresql://{env.user}@127.0.0.1:{env.port}/{env.dbname}"

    monkeypatch.setenv("ARIS_PG_DSN", "postgresql://u@example/other")
    assert detect(tmp_path / "data").dsn == "postgresql://u@example/other"

    tool_env = env.tool_env()
    assert tool_env["PGHOST"] == str(env.run_dir)
    assert tool_env["PGPORT"] == str(env.port)


def test_unknown_embedding_provider():
    """未知 provider 给出可读错误（不触发重依赖导入）。"""
    with pytest.raises(EmbeddingError):
        get_provider("cloudflare")


def test_local_provider_metadata_without_deps(tmp_path):
    """本地 provider 的元数据不需要加载模型即可读到。"""
    provider = LocalBekkoProvider(data_dir=tmp_path)

    assert provider.dimension == BEKKO_A25M_DIM
    assert provider.name == "local:bekko-embedding-v1-a25m"
    assert provider.embed([]) == []  # 空输入不加载模型

    truncated = LocalBekkoProvider(data_dir=tmp_path, truncate_dim=256)
    assert truncated.dimension == 256


def test_is_running_requires_real_probe(tmp_path, monkeypatch):
    """仅凭 pg_ctl status 不够：残留 pidfile 会让它误报，须由 pg_isready 实测。

    pg_isready 退出码：0 接受连接、1 在线但拒绝本次探测（如默认库不存在/启动中）、
    2 无响应——只有 0/1 算在跑，否则「库还没建好」时会被误判成没起。
    """
    import importlib

    # 注意：store/__init__ 会重导出 bootstrap_env，故这里必须按模块路径取
    bootstrap_mod = importlib.import_module("aris.store.bootstrap")
    from aris.store.pgenv import detect

    bin_dir = _fake_bin(tmp_path / "pg")
    for name in ("pg_ctl", "pg_isready"):
        (bin_dir / name).write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("ARIS_PG_BIN", str(bin_dir))
    env = detect(tmp_path / "data")
    (env.pgdata).mkdir(parents=True, exist_ok=True)
    (env.pgdata / "PG_VERSION").write_text("17\n", encoding="utf-8")

    state = {"codes": iter([0, 2])}  # pg_ctl status=在跑，pg_isready=无响应

    class _Result:
        returncode = 0

    def _fake_run(cmd, **_kwargs):
        _Result.returncode = next(state["codes"])
        return _Result()

    monkeypatch.setattr(bootstrap_mod.subprocess, "run", _fake_run)
    assert bootstrap_mod.is_running(env) is False  # 无响应 → 没在跑

    state["codes"] = iter([0, 0])
    assert bootstrap_mod.is_running(env) is True

    state["codes"] = iter([0, 1])  # 在线但拒绝（如库不存在）
    assert bootstrap_mod.is_running(env) is True


def test_start_clears_stale_pidfile(tmp_path, monkeypatch):
    """崩溃后残留的 postmaster.pid 会挡住 pg_ctl 启动，要先清掉。"""
    import importlib

    bootstrap_mod = importlib.import_module("aris.store.bootstrap")
    from aris.store.pgenv import detect

    bin_dir = _fake_bin(tmp_path / "pg")
    for name in ("pg_ctl", "pg_isready"):
        (bin_dir / name).write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("ARIS_PG_BIN", str(bin_dir))
    env = detect(tmp_path / "data")
    env.pgdata.mkdir(parents=True, exist_ok=True)
    (env.pgdata / "PG_VERSION").write_text("17\n", encoding="utf-8")
    pid_file = env.pgdata / "postmaster.pid"
    pid_file.write_text("12\n", encoding="utf-8")  # 残留

    calls: list[str] = []

    class _Result:
        returncode = 0
        stderr = ""
        stdout = ""

    def _fake_run(cmd, **_kwargs):
        calls.append(str(cmd[0]).rsplit("/", 1)[-1])
        _Result.returncode = 0 if "start" in cmd else 1  # status → 未运行；start → 成功
        return _Result()

    monkeypatch.setattr(bootstrap_mod.subprocess, "run", _fake_run)
    assert bootstrap_mod.start(env) is True

    assert not pid_file.exists()  # 残留被清理
    assert calls == ["pg_ctl", "pg_ctl"]  # status 探测 + start


def test_store_services_registered():
    """store 模块 import 时自注册总线服务。"""
    import aris.store  # noqa: F401

    assert bus.has_service("store.health")
    assert bus.has_service("store.embed")
