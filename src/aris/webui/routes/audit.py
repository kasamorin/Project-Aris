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
        import time
        records = query_recent(limit=page_size)
        result = []
        for r in records:
            # 过滤
            target_parts = r.target.split(".")
            mod = target_parts[0] if target_parts else r.target
            if module and mod != module:
                continue
            if action and action not in r.target:
                continue
            # 将 monotonic 时间戳转为可读时间（近似）
            ts_str = time.strftime("%H:%M:%S")
            result.append({
                "ts": ts_str,
                "module": mod,
                "action": r.target,
                "result": "success" if r.ok else "error",
                "detail": f"{r.duration*1000:.0f}ms" + (f" {r.detail}" if r.detail else ""),
            })
        return result
    except Exception as e:
        from loguru import logger
        logger.warning(f"审计查询失败: {e}")
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
