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
