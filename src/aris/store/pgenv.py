"""PostgreSQL 环境探测：定位可用实例并拼装连接参数。

探针链（按序命中即终止，定案见 developDoc/KNOWLEDGE-BASE.md 第 3.1 节）：

1. 环境变量 ``ARIS_PG_BIN``（显式覆盖，指向外部安装的 bin 目录）
2. PATH 中的 ``pg_config``（系统已装则直接用）
3. 项目内 ``data/pg/bin/postgres``（bootstrap 自动装的便携实例）
4. 全无 → 视为未安装，提示先跑 ``aris db init``

可覆盖的环境变量：``ARIS_PG_BIN`` / ``ARIS_PG_PORT`` / ``ARIS_PG_USER`` /
``ARIS_PG_DB`` / ``ARIS_PG_DSN``（整条 DSN 直用，优先级最高）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

DEFAULT_PORT = 55432
DEFAULT_DB = "aris"
PROJECT_DIR_NAME = "pg"  # 便携实例根目录：<data_dir>/pg
PGDATA_NAME = "pgdata"  # 数据目录：<data_dir>/pgdata


class PgSource(StrEnum):
    """PostgreSQL 实例来源。"""

    ENV = "env"  # ARIS_PG_BIN 指定
    SYSTEM = "system"  # PATH 中的 pg_config（系统安装）
    PROJECT = "project"  # data/pg（本项目 bootstrap 安装）
    MISSING = "missing"  # 未找到任何可用实例


@dataclass(frozen=True)
class PgEnv:
    """一个 PostgreSQL 实例的运行参数（探测结果 + 本项目约定）。"""

    source: PgSource
    prefix: Path  # 便携实例根目录（<data_dir>/pg）
    bin_dir: Path | None  # 可执行文件目录；未安装时为 None
    pgdata: Path  # 数据目录（<data_dir>/pgdata）
    run_dir: Path  # unix socket 目录（<data_dir>/pg/run）
    log_file: Path  # 服务日志（<data_dir>/pg/postgres.log）
    port: int
    user: str
    dbname: str

    @property
    def installed(self) -> bool:
        """是否已找到可用的 PostgreSQL 可执行文件。"""
        return self.bin_dir is not None

    def tool(self, name: str) -> Path:
        """返回实例内某个可执行文件的路径（未安装时报错）。"""
        if self.bin_dir is None:
            raise RuntimeError("PostgreSQL 未安装，请先运行 aris db init")
        return self.bin_dir / name

    @property
    def dsn(self) -> str:
        """连接串：``ARIS_PG_DSN`` 优先，否则按本地 TCP 拼装。"""
        override = os.environ.get("ARIS_PG_DSN")
        if override:
            return override
        return f"postgresql://{self.user}@127.0.0.1:{self.port}/{self.dbname}"

    def tool_env(self) -> dict[str, str]:
        """psql/createdb 等工具的环境变量（走 unix socket，不依赖 TCP 监听）。"""
        return {
            **os.environ,
            "PGHOST": str(self.run_dir),
            "PGPORT": str(self.port),
            "PGUSER": self.user,
            "PGDATABASE": self.dbname,
        }


def _data_dir() -> Path:
    """取全局配置里的数据目录（延迟 import，避免配置层反向依赖本模块）。"""
    from ..config import get_settings

    return Path(get_settings().data_dir)


def _pg_config_bindir(pg_config: str) -> Path | None:
    """由 ``pg_config --bindir`` 得到系统 PostgreSQL 的可执行文件目录。"""
    try:
        out = subprocess.run(
            [pg_config, "--bindir"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    bindir = out.stdout.strip()
    return Path(bindir) if bindir else None


def _probe_bin(prefix: Path) -> tuple[Path | None, PgSource]:
    """按探针链找可执行文件目录，返回 (bin_dir, 来源)。"""
    env_bin = os.environ.get("ARIS_PG_BIN")
    if env_bin and (Path(env_bin) / "postgres").exists():
        return Path(env_bin), PgSource.ENV

    pg_config = shutil.which("pg_config")
    if pg_config:
        bindir = _pg_config_bindir(pg_config)
        if bindir and (bindir / "postgres").exists():
            return bindir, PgSource.SYSTEM

    project_bin = prefix / "bin"
    if (project_bin / "postgres").exists():
        return project_bin, PgSource.PROJECT

    return None, PgSource.MISSING


def detect(data_dir: Path | None = None) -> PgEnv:
    """执行探针链，返回当前应使用的 PostgreSQL 环境。

    路径一律转成**绝对路径**：PostgreSQL 启动后会 chdir 到数据目录，``-k``/``-D``
    传相对路径会被解析到错误位置。
    """
    root = Path(data_dir) if data_dir is not None else _data_dir()
    if not root.is_absolute():
        root = Path.cwd() / root
    root = root.resolve()
    prefix = root / PROJECT_DIR_NAME
    bin_dir, source = _probe_bin(prefix)
    return PgEnv(
        source=source,
        prefix=prefix,
        bin_dir=bin_dir,
        pgdata=root / PGDATA_NAME,
        run_dir=prefix / "run",
        log_file=prefix / "postgres.log",
        port=int(os.environ.get("ARIS_PG_PORT", DEFAULT_PORT)),
        user=os.environ.get("ARIS_PG_USER") or os.environ.get("USER") or "postgres",
        dbname=os.environ.get("ARIS_PG_DB", DEFAULT_DB),
    )
