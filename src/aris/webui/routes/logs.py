"""日志查看路由——历史日志文件浏览 + SSE 实时日志流。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from ..templates import render

router = APIRouter()


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(
    request: Request,
    file: str | None = Query(None),
    date: str | None = Query(None),
) -> HTMLResponse:
    """日志查看页面。"""
    from ...config import get_settings
    settings = get_settings()

    import datetime
    if date is None:
        date = datetime.date.today().isoformat()

    log_dir = settings.data_dir / "logs" / date
    log_files = []
    if log_dir.exists():
        for f in sorted(log_dir.iterdir(), reverse=True):
            if f.is_file() and f.name.startswith("aris"):
                log_files.append({"name": f.name})

    log_content = ""
    if file and log_dir.exists():
        log_path = log_dir / file
        if log_path.exists():
            log_content = log_path.read_text(encoding="utf-8", errors="replace")

    return render(request, "logs.html", {
        "active_page": "logs",
        "log_files": log_files,
        "current_file": file,
        "log_content": log_content,
    })
