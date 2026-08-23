"""日志查看路由——历史日志文件浏览 + SSE 实时日志流。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from ..templates import render

router = APIRouter()


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(
    request: Request,
    file: str | None = Query(None),
    date: str | None = Query(None),
    page: int = Query(1, ge=1),
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
    total_lines = 0
    if file and log_dir.exists():
        log_path = log_dir / file
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            total_lines = len(lines)
            # 分页：每页 200 行，显示最新的
            page_size = 200
            start = max(0, total_lines - page * page_size)
            end = start + page_size
            log_content = "\n".join(lines[start:end])

    total_pages = max(1, (total_lines + 199) // 200) if total_lines else 1

    return render(request, "logs.html", {
        "active_page": "logs",
        "log_files": log_files,
        "current_file": file,
        "log_content": log_content,
        "page": page,
        "total_pages": total_pages,
        "total_lines": total_lines,
        "date": date,
    })


@router.get("/logs/stream")
async def logs_stream(request: Request) -> StreamingResponse:
    """日志实时流 SSE 端点。"""
    from ..sse import log_broker

    queue = log_broker.subscribe()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = queue.get_nowait()
                    yield event
                except Exception:
                    await asyncio.sleep(0.5)
        finally:
            log_broker.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
