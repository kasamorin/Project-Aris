"""请求日志中间件——把 HTTP 请求通过 loguru 记录，SSE 可捕获。"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """记录每个 HTTP 请求到 loguru，供 SSE 实时流捕获。"""

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        """中间件入口：计时并把每个页面请求写到 loguru，静态资源跳过。"""
        start = time.time()
        response = await call_next(request)
        duration = (time.time() - start) * 1000

        # 只记录页面请求，不记录静态资源
        path = request.url.path
        if not path.startswith("/static"):
            logger.info(
                f"{request.method} {path} → {response.status_code} ({duration:.0f}ms)"
            )

        return response
