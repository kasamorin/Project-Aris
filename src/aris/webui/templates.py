"""Jinja2 模板渲染工具。"""

from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader

# 模板目录
_TEMPLATE_DIR = Path(__file__).parent / "templates"

# Jinja2 环境（全局复用）
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=True,  # 防 XSS
)


def render(
    request: Request,
    template_name: str,
    context: dict | None = None,
) -> HTMLResponse:
    """渲染 Jinja2 模板并返回 HTMLResponse。"""
    template = _env.get_template(template_name)
    html = template.render(request=request, **(context or {}))
    return HTMLResponse(content=html)
