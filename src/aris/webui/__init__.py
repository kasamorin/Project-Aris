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

    # 导入总线服务所有者模块以触发 provide 注册（不直接调用其函数）。
    # routes 统一经 core.call 取用，这是注册触发点，非跨模块业务调用。
    from aris.core.llm import fetch as _llm_fetch_svc  # noqa: F401  (llm.fetch.* / llm.retired.*)
    from aris.core.llm import manage as _llm_manage_svc  # noqa: F401  (llm.providers.*)
    from aris.behavior.skills import manager as _skills_svc  # noqa: F401  (skills.*)
    _verify_bus_services()

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


# webui 依赖的总线服务清单（create_app 时校验，缺注册即记错误方便排查）
_REQUIRED_SERVICES = (
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
)


def _verify_bus_services() -> None:
    """启动时校验 webui 所需的全部总线服务均已注册。"""
    from aris.core import has_service

    missing = [s for s in _REQUIRED_SERVICES if not has_service(s)]
    if missing:
        from loguru import logger
        logger.error(
            f"WebUI 依赖的总线服务未注册: {', '.join(missing)}——"
            "请检查总线服务所有者模块是否正确导入"
        )
