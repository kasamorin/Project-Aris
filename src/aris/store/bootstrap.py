"""便携 PostgreSQL + pgvector 的获取与初始化（幂等）。

不要求用户预装系统 PostgreSQL（定案见 developDoc/KNOWLEDGE-BASE.md 第 3 节）：
缺什么补什么——下载 micromamba（含 sha256 校验）→ 在 ``data/pg`` 建 conda 环境
（``postgresql`` 与 ``pgvector`` 同源，版本匹配由 solver 保证）→ ``initdb`` →
启动 → 建库 → 建 ``vector`` 扩展。全部产物落在 ``data/`` 下（gitignore 已覆盖），
仓库零体积增长；代码只认连接串，不感知实例来源。
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import urllib.request
from pathlib import Path

from loguru import logger

from .pgenv import PgEnv, PgSource, detect

# micromamba 固定版本 + 官方 sha256（升级时两处一起人工更新）
MAMBA_VERSION = "2.9.0-0"
MAMBA_URL = (
    "https://github.com/mamba-org/micromamba-releases/releases/download/"
    f"{MAMBA_VERSION}/micromamba-linux-64"
)
MAMBA_SHA256 = "366cd9cd8be14df1ab8ed50352a82111082a36686b2d389fdb79a92c3fafb3e3"

PG_VERSION = "17"
PGVECTOR_SPEC = "pgvector>=0.8"
CONDA_CHANNEL = "conda-forge"

DOWNLOAD_TIMEOUT = 600  # 秒；conda 环境首次下载可能较慢
CHUNK_SIZE = 1 << 20


class BootstrapError(RuntimeError):
    """bootstrap 过程中的可读错误（下载失败 / 命令失败 / 校验失败）。"""


def _sha256(path: Path) -> str:
    """计算文件 sha256（分块读取，避免整包进内存）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> str:
    """执行外部命令；失败抛 :class:`BootstrapError`（带 stderr 末尾几行）。"""
    logger.debug(f"执行: {' '.join(cmd)}")
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        lines = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = " / ".join(lines[-3:]) if lines else f"退出码 {proc.returncode}"
        raise BootstrapError(f"{Path(cmd[0]).name} 执行失败：{tail}")
    return proc.stdout


def mamba_path(env: PgEnv) -> Path:
    """micromamba 的落地位置（放在便携实例的同级 bin 目录，避开环境自身）。"""
    return env.prefix.parent / "bin" / "micromamba"


def ensure_micromamba(env: PgEnv) -> Path:
    """确保 micromamba 就位：已存在且 sha256 匹配则复用，否则下载校验。"""
    dest = mamba_path(env)
    if dest.exists() and _sha256(dest) == MAMBA_SHA256:
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    logger.info(f"下载 micromamba {MAMBA_VERSION} ...")
    try:
        with urllib.request.urlopen(MAMBA_URL, timeout=DOWNLOAD_TIMEOUT) as resp:
            with open(tmp, "wb") as fh:
                shutil.copyfileobj(resp, fh)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise BootstrapError(f"下载 micromamba 失败：{exc}") from exc

    digest = _sha256(tmp)
    if digest != MAMBA_SHA256:
        tmp.unlink(missing_ok=True)
        raise BootstrapError(
            f"micromamba sha256 不匹配：期望 {MAMBA_SHA256}，实际 {digest}"
        )
    tmp.chmod(0o755)
    tmp.replace(dest)
    logger.success(f"micromamba 就位：{dest}")
    return dest


def ensure_pg_env(env: PgEnv, mamba: Path) -> None:
    """确保 conda 环境内已装 postgresql + pgvector（已装则跳过）。"""
    if (env.prefix / "bin" / "postgres").exists():
        return
    logger.info(f"安装 PostgreSQL {PG_VERSION} + pgvector 到 {env.prefix}（首次约 40MB）...")
    # 根前缀、包缓存、libmamba 元数据缓存全部收在 data/ 下：
    # 不污染用户主目录，清理时随 data/ 一起走。
    # micromamba 仍会写 ~/.conda/environments.txt 与 ~/.mambarc，故把 HOME 也指到 data/。
    root = env.prefix.parent
    mamba_env = {
        **env.tool_env(),
        "MAMBA_ROOT_PREFIX": str(root / "pg-root"),
        "CONDA_PKGS_DIRS": str(root / "pg-pkgs"),
        "XDG_CACHE_HOME": str(root / ".cache"),
        "HOME": str(root / ".home"),
    }
    _run(
        [
            str(mamba),
            "create",
            "-y",
            "-p",
            str(env.prefix),
            "-c",
            CONDA_CHANNEL,
            f"postgresql={PG_VERSION}",
            PGVECTOR_SPEC,
        ],
        env=mamba_env,
    )


def ensure_cluster(env: PgEnv) -> None:
    """``initdb`` 初始化数据目录（已初始化则跳过）。"""
    if (env.pgdata / "PG_VERSION").exists():
        return
    env.pgdata.mkdir(parents=True, exist_ok=True)
    env.run_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"初始化数据目录 {env.pgdata} ...")
    _run(
        [
            str(env.tool("initdb")),
            "-D",
            str(env.pgdata),
            "-U",
            env.user,
            "--encoding=UTF8",
            "--no-locale",  # 避免依赖宿主 locale；排序用 C
            "--auth-local=trust",
            "--auth-host=trust",
        ]
    )
    logger.success("数据目录初始化完成")


def is_running(env: PgEnv) -> bool:
    """实例是否正在运行（未安装或未初始化一律视为未运行）。

    只看 ``pg_ctl status`` 不够：崩溃后残留的 ``postmaster.pid``（PID 被复用、
    或换了 PID 命名空间）会让它报"在运行"。故再用 ``pg_isready`` 真实探一次——
    连接被拒即认定未运行，避免 ``aris db start`` 因此拒绝启动。
    """
    if not env.installed or not (env.pgdata / "PG_VERSION").exists():
        return False
    proc = subprocess.run(
        [str(env.tool("pg_ctl")), "-D", str(env.pgdata), "status"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return False
    ready = subprocess.run(
        [str(env.tool("pg_isready")), "-h", str(env.run_dir), "-p", str(env.port)],
        capture_output=True,
        text=True,
    )
    return ready.returncode == 0


def _log_tail(env: PgEnv, lines: int = 5) -> str:
    """读服务日志末尾若干行，用于启动失败时的诊断。"""
    if not env.log_file.exists():
        return ""
    tail = env.log_file.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    return " / ".join(tail[-lines:])


def start(env: PgEnv) -> bool:
    """启动服务；已在运行则返回 False（无操作）。"""
    if is_running(env):
        return False
    env.run_dir.mkdir(parents=True, exist_ok=True)
    env.log_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run(
            [
                str(env.tool("pg_ctl")),
                "-D",
                str(env.pgdata),
                "-l",
                str(env.log_file),
                "-o",
                f"-p {env.port} -k {env.run_dir} -h 127.0.0.1",
                "-w",
                "-t",
                "60",
                "start",
            ]
        )
    except BootstrapError as exc:
        # pg_ctl 自身信息很少，把服务日志末尾一起抛出便于定位
        raise BootstrapError(f"{exc}；服务日志：{_log_tail(env)}") from exc
    return True


def stop(env: PgEnv) -> bool:
    """停止服务；本就未运行则返回 False（无操作）。"""
    if not is_running(env):
        return False
    _run([str(env.tool("pg_ctl")), "-D", str(env.pgdata), "-m", "fast", "-w", "stop"])
    return True


def ensure_database(env: PgEnv) -> None:
    """建库 + 建 ``vector`` 扩展（幂等）。"""
    psql = str(env.tool("psql"))
    tool_env = env.tool_env()
    probe_env = {**tool_env, "PGDATABASE": "postgres"}  # 目标库可能尚不存在
    exists = _run(
        [psql, "-tAc", f"SELECT 1 FROM pg_database WHERE datname = '{env.dbname}'"],
        env=probe_env,
    ).strip()
    if not exists:
        logger.info(f"创建数据库 {env.dbname} ...")
        _run([str(env.tool("createdb")), env.dbname], env=tool_env)
    _run(
        [psql, "-d", env.dbname, "-c", "CREATE EXTENSION IF NOT EXISTS vector"],
        env=tool_env,
    )


def write_versions(env: PgEnv) -> Path:
    """把当前实例版本写入 ``<prefix>/versions.txt``，便于日后排查。"""
    psql = str(env.tool("psql"))
    tool_env = env.tool_env()
    server = _run([psql, "-tAc", "SHOW server_version"], env=tool_env).strip()
    vector = _run(
        [
            psql,
            "-tAc",
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'",
        ],
        env=tool_env,
    ).strip()
    target = env.prefix / "versions.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"postgresql={server}\npgvector={vector or 'missing'}\n"
        f"provider={env.source}\nport={env.port}\ndb={env.dbname}\n",
        encoding="utf-8",
    )
    return target


def bootstrap_env(env: PgEnv) -> PgEnv:
    """一条龙：探测 → 装 micromamba → 装 PG + pgvector → initdb → 启动 → 建库。

    系统已装（``ARIS_PG_BIN`` / ``pg_config``）时**不下载**，只确保库与扩展存在。
    返回可能已刷新的 :class:`PgEnv`（刚装完便携实例时来源与 bin 目录会变）。

    命名带 ``_env`` 后缀是刻意的：函数若与模块同名（``bootstrap``），
    包内 ``from .bootstrap import bootstrap`` 会把它遮蔽成模块属性，
    调用方 ``store.bootstrap`` 拿到的就不是模块了（已踩过）。
    """
    if env.source in (PgSource.ENV, PgSource.SYSTEM):
        logger.info(f"使用已有 PostgreSQL 实例（{env.bin_dir}），跳过下载")
    else:
        mamba = ensure_micromamba(env)
        ensure_pg_env(env, mamba)
        env = detect(env.prefix.parent)  # 装好后 bin_dir 才存在，重新探测

    ensure_cluster(env)
    if start(env):
        logger.success(f"数据库已启动（端口 {env.port}）")
    else:
        logger.info(f"数据库已在运行（端口 {env.port}）")
    ensure_database(env)
    versions = write_versions(env)
    logger.success(f"数据库就绪：{env.dsn}")
    logger.info(f"版本清单：{versions}")
    return env
