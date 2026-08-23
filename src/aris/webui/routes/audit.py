"""审计流水路由——查询/筛选 + SSE 实时流。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from ..templates import render

router = APIRouter()


@router.get("/audit", response_class=HTMLResponse)
async def audit_page(
    request: Request,
    module: str | None = Query(None),
    action: str | None = Query(None),
    page: int = Query(1, ge=1),
) -> HTMLResponse:
    """审计流水页面。"""
    records = _query_records(module=module, action=action, page=page)
    return render(request, "audit.html", {
        "active_page": "audit",
        "records": records,
    })


def _query_records(
    module: str | None = None,
    action: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> list[dict]:
    """查询审计记录。"""
    try:
        from ...core.audit import query_recent
        records = query_recent(limit=page_size)
        result = []
        for r in records:
            # 过滤
            if module and r.target.split(".")[0] != module:
                continue
            if action and action not in r.target:
                continue
            result.append({
                "ts": f"{r.duration*1000:.0f}ms",
                "module": r.target.split(".")[0] if "." in r.target else r.target,
                "action": r.target,
                "result": "success" if r.ok else "error",
                "detail": r.detail or "",
            })
        return result
    except Exception:
        pass
    return []


@router.get("/audit/stream")
async def audit_stream(request: Request) -> StreamingResponse:
    """审计实时流 SSE 端点。"""
    from ..sse import audit_broker

    queue = audit_broker.subscribe()

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
            audit_broker.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
