"""审计流水路由——查询/筛选 + SSE 实时流。"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

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
        from ...core import call
        result = call(
            "audit.query_recent",
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        if result:
            return result if isinstance(result, list) else []
    except Exception:
        pass
    return []
