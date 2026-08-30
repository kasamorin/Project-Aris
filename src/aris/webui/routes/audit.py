"""审计流水路由——查询/筛选 + SSE 实时流。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

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
    total = _count_records(module=module, action=action)
    total_pages = max(1, (total + 49) // 50)
    return render(request, "audit.html", {
        "active_page": "audit",
        "records": records,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "module": module or "",
        "action": action or "",
    })


def _query_records(
    module: str | None = None,
    action: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> list[dict]:
    """查询审计记录（先过滤后分页，page=1 为最新一页）。"""
    try:
        import datetime

        from aris.core import call

        # 拉取足够覆盖目标页的记录数，再切片出该页窗口
        records = call("audit.recent", page * page_size) or []
        matched = [
            r for r in records
            if _record_matches(r, module, action)
        ]
        window = matched[(page - 1) * page_size: page * page_size]
        result = []
        for r in window:
            wall = getattr(r, "wall_ts", None)
            ts_str = (
                datetime.datetime.fromtimestamp(wall).strftime("%H:%M:%S")
                if wall else "-"
            )
            target_parts = r.target.split(".")
            mod = target_parts[0] if target_parts else r.target
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


def _record_matches(r: object, module: str | None, action: str | None) -> bool:
    """按模块/动作筛选一条审计记录。"""
    target = r.target  # type: ignore[attr-defined]
    target_parts = target.split(".")
    mod = target_parts[0] if target_parts else target
    if module and mod != module:
        return False
    if action and action not in target:
        return False
    return True


def _count_records(module: str | None = None, action: str | None = None) -> int:
    """统计筛选后的记录总数（上限为环形缓冲容量）。"""
    try:
        from aris.core import call
        records = call("audit.recent", None) or []  # 全量（受 max_records 环形缓冲约束）
        return sum(1 for r in records if _record_matches(r, module, action))
    except Exception as e:
        from loguru import logger
        logger.warning(f"审计计数失败: {e}")
        return 0


@router.get("/audit/stream")
async def audit_stream(request: Request) -> StreamingResponse:
    """审计实时流 SSE 端点。"""
    from ..sse import audit_broker

    queue = audit_broker.subscribe()

    async def event_generator() -> AsyncGenerator[str, None]:
        """SSE 事件生成器：实时推送审计事件，断连即退出。"""
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
