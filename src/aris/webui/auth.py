"""鉴权中间件——密码登录 + HMAC 签名 cookie session。

密码来源：.env 的 ARIS_WEBUI_PASSWORD。
会话：aris_session cookie，payload 含签发时间 + 过期时间，HMAC-SHA256 签名。
未配置密码时拒绝登录（不裸奔）。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse

# HMAC 签名密钥：从环境变量取，不存在时用随机值（每次重启失效——合理，运维场景）
_SECRET = os.environ.get("ARIS_WEBUI_HMAC_SECRET", secrets.token_hex(32))
_COOKIE_NAME = "aris_session"
_DEFAULT_MAX_AGE = 7 * 24 * 3600  # 7 天

# 不需要鉴权的路径
_PUBLIC_PATHS = {"/login", "/static"}


def _sign(payload: str) -> str:
    """HMAC-SHA256 签名。"""
    return hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_session_cookie(max_age: int = _DEFAULT_MAX_AGE) -> tuple[str, int]:
    """创建签名 session cookie 值：payload.signature，返回 (value, max_age)。"""
    now = int(time.time())
    payload = f"{now}.{now + max_age}"
    sig = _sign(payload)
    return f"{payload}.{sig}", max_age


def verify_session(cookie_value: str) -> bool:
    """验证 session cookie 签名与过期时间。"""
    parts = cookie_value.split(".")
    if len(parts) != 3:
        return False
    payload, sig = f"{parts[0]}.{parts[1]}", parts[2]
    if not hmac.compare_digest(sig, _sign(payload)):
        return False
    try:
        issued, expires = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return time.time() < expires


def is_password_configured() -> bool:
    """检查 ARIS_WEBUI_PASSWORD 是否已配置。"""
    return bool(os.environ.get("ARIS_WEBUI_PASSWORD"))


def check_password(password: str) -> bool:
    """验证密码。使用 secrets.compare_digest 防时序攻击。"""
    expected = os.environ.get("ARIS_WEBUI_PASSWORD", "")
    if not expected:
        return False
    return secrets.compare_digest(password, expected)


class AuthMiddleware(BaseHTTPMiddleware):
    """HTTP 中间件：未登录请求重定向到 /login。"""

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        # 公开路径跳过鉴权
        path = request.url.path
        if any(path.startswith(p) for p in _PUBLIC_PATHS):
            return await call_next(request)

        # 检查 session cookie
        cookie = request.cookies.get(_COOKIE_NAME)
        if cookie and verify_session(cookie):
            return await call_next(request)

        # 未登录 → 重定向到登录页
        return RedirectResponse(url="/login", status_code=302)
