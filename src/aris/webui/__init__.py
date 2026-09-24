"""WebUI 管理后台——FastAPI 应用工厂。

定位为内部运维管理面板（非对话界面），默认绑定 0.0.0.0，密码鉴权必设。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..core import provide
from .auth import AuthMiddleware


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。

    总线服务的注册由**组装根**负责（`aris serve` / `aris web` 都走
    `serve.assemble()`，测试走 `tests/conftest.py`）——本函数只搭 HTTP 层，
    不再自己 import 各模块：同一份「需要哪些服务」的清单散在多处必然漂移
    （见 developDoc/SERVE.md 第 7 节）。依赖清单仍由本模块声明
    （:data:`REQUIRED_SERVICES`），交给 serve 的 `services` 步骤统一校验。
    """
    app = FastAPI(
        title="Project-Aris WebUI",
        docs_url=None,  # 管理后台不暴露 Swagger
        redoc_url=None,
    )

    # 安装 loguru SSE sink（必须在其他中间件之前）
    from .sse import install_loguru_sink
    install_loguru_sink()

    # 请求日志中间件（通过 loguru 记录，SSE 可捕获）
    from .middleware import RequestLoggingMiddleware
    app.add_middleware(RequestLoggingMiddleware)

    # 鉴权中间件
    app.add_middleware(AuthMiddleware)

    # 静态资源（UnoCSS + marked.js）
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # 模板目录
    templates_dir = Path(__file__).parent / "templates"

    # 注册路由
    from .routes import dashboard, audit, providers, skills, config, logs, history
    from .routes import knowledge as knowledge_route

    app.include_router(dashboard.router)
    app.include_router(audit.router)
    app.include_router(providers.router)
    app.include_router(skills.router)
    app.include_router(knowledge_route.router)
    app.include_router(config.router)
    app.include_router(logs.router)
    app.include_router(history.router)

    # 登录/登出（不走鉴权中间件）
    from .routes import auth as auth_route

    app.include_router(auth_route.router)

    return app


# webui 依赖的总线服务清单（本模块声明；serve 的 `services` 步骤启动时校验）
REQUIRED_SERVICES = (
    "audit.recent",
    "audit.summary",
    "llm.providers.load",
    "llm.providers.add",
    "llm.providers.delete",
    "llm.providers.model_add",
    "llm.providers.model_delete",
    "llm.fetch.plan",
    "llm.fetch.apply",
    "llm.retired.list",
    "llm.retired.delete",
    "skills.list",
    "skills.detail",
    "skills.create",
    "skills.save",
    "skills.delete",
    "knowledge.ingest",
    "knowledge.sources",
    "knowledge.remove",
    "knowledge.search",
    "knowledge.reindex",
    "knowledge.upload",
    "knowledge.status",
    "store.vector.count",
)


def port_in_use(host: str, port: int) -> bool:
    """端口是否已被占用（启动前的冲突检测，见 developDoc/SERVE.md 第 4 节）。"""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return True
    return False


def _resolve_bind(host: str | None = None, port: int | None = None) -> tuple[str, int, str]:
    """解析监听地址：`config/webui.toml` → 免鉴权护栏；返回 (host, port, 警告文案)。"""
    from dataclasses import dataclass

    from aris.cfgtoml import load_config

    @dataclass
    class WebUIConfig:
        host: str = "0.0.0.0"
        port: int = 9690

    web_config = load_config(WebUIConfig(), "webui.toml")
    from .auth import resolve_bind_host

    bind_host, warning = resolve_bind_host(host or web_config.host)
    return bind_host, int(port or web_config.port), warning


def probe_server() -> dict[str, Any]:
    """总线服务：WebUI 启动探针（只读，不创建应用、不占端口）。"""
    host, port, warning = _resolve_bind()
    return {
        "host": host,
        "port": port,
        "available": not port_in_use(host, port),
        "warning": warning,
    }


def start_server(host: str | None = None, port: int | None = None) -> str:
    """总线服务：启动 WebUI 管理后台（**阻塞**，`aris web` 与 `aris serve` 共用）。

    端口被占用（多半是另一个 `aris web` / `aris serve` 在跑）时抛 RuntimeError，
    由调用方决定是拒绝启动 webui 还是整体退出——见 developDoc/SERVE.md 第 4 节。
    """
    import uvicorn
    from loguru import logger

    bind_host, bind_port, warning = _resolve_bind(host, port)
    if warning:
        logger.warning(warning)
    if port_in_use(bind_host, bind_port):
        raise RuntimeError(
            f"端口 {bind_host}:{bind_port} 已被占用，"
            "可能是另一个 `aris web` / `aris serve` 在运行"
        )
    from .auth import is_password_configured

    app = create_app()
    if not is_password_configured():
        logger.warning("WebUI 运行在免鉴权模式：任何能访问该地址的请求都视为已登录")
    logger.info(f"WebUI 启动：http://{bind_host}:{bind_port}")
    uvicorn.run(app, host=bind_host, port=bind_port, log_level="info")
    return f"http://{bind_host}:{bind_port}"


# 启动动作由 webui 自己提供（serve 只经总线调用，不代它做事）
provide("webui.probe", probe_server)
provide("webui.start", start_server)
