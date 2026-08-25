"""登录/登出路由。

GET /login → 登录页面
POST /login → 验证密码 + 限流 + 签发 cookie
GET /logout → 清除 cookie + 重定向
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..auth import (
    check_password,
    create_session_cookie,
    is_password_configured,
)
from ..rate_limit import login_limiter

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    """登录页面。"""
    from ..templates import render

    return render(request, "login.html", {"error": None})


@router.post("/login", response_model=None)
async def login_submit(
    request: Request,
    password: str = Form(...),
) -> RedirectResponse | HTMLResponse:
    """处理登录表单提交。"""
    from ..templates import render

    client_ip = request.client.host if request.client else "unknown"

    # 检查密码是否配置
    if not is_password_configured():
        return render(
            request,
            "login.html",
            {"error": "未配置密码，请在 .env 中设置 ARIS_WEBUI_PASSWORD"},
        )

    # 限流检查
    if login_limiter.is_locked(client_ip):
        return render(
            request,
            "login.html",
            {"error": "登录尝试过多，请稍后再试"},
        )

    # 验证密码
    if not check_password(password):
        login_limiter.record_failure(client_ip)
        return render(
            request,
            "login.html",
            {"error": "密码错误"},
        )

    # 登录成功
    login_limiter.reset(client_ip)
    cookie_value, max_age = create_session_cookie()
    response = RedirectResponse(url="/", status_code=303)  # 303 改为 GET
    response.set_cookie(
        "aris_session",
        cookie_value,
        max_age=max_age,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/logout")
async def logout() -> RedirectResponse:
    """登出：清除 cookie 并重定向到登录页。"""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("aris_session")
    return response
