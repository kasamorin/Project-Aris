"""对话历史路由——占位页，待大会话机制落地后补充。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..templates import render

router = APIRouter()


@router.get("/history", response_class=HTMLResponse)
async def history_page(request: Request) -> HTMLResponse:
    """对话历史占位页。"""
    return render(request, "history.html", {
        "active_page": "history",
    })
