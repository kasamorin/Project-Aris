"""WebUI 管理后台——FastAPI 应用工厂。

定位为内部运维管理面板（非对话界面），默认绑定 0.0.0.0，密码鉴权必设。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..config import get_settings
from .auth import AuthMiddleware


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""
    settings = get_settings()

    app = FastAPI(
        title="Project-Aris WebUI",
        docs_url=None,  # 管理后台不暴露 Swagger
        redoc_url=None,
    )

    # 鉴权中间件
    app.add_middleware(AuthMiddleware)

    # 安装 loguru SSE sink
    from .sse import install_loguru_sink
    install_loguru_sink()

    # 静态资源（UnoCSS + marked.js）
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # 模板目录
    templates_dir = Path(__file__).parent / "templates"

    # 注册路由
    from .routes import dashboard, audit, providers, skills, config, logs, history

    app.include_router(dashboard.router)
    app.include_router(audit.router)
    app.include_router(providers.router)
    app.include_router(skills.router)
    app.include_router(config.router)
    app.include_router(logs.router)
    app.include_router(history.router)

    # 登录/登出（不走鉴权中间件）
    from .routes import auth as auth_route

    app.include_router(auth_route.router)

    return app
