"""仪表盘路由——聚合统计 + 系统状态 + 快捷入口。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..templates import render

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """仪表盘首页。"""
    stats = _gather_stats()
    return render(request, "dashboard.html", {
        "active_page": "dashboard",
        "stats": stats,
    })


def _gather_stats() -> dict:
    """收集仪表盘统计数据。"""
    from pathlib import Path
    from ...config import get_settings

    settings = get_settings()
    today = Path(__file__).now().strftime("%Y-%m-%d") if False else ""
    # 简单实现：统计今日对话文件数
    import datetime
    today = datetime.date.today().isoformat()
    log_dir = settings.data_dir / "logs" / today
    chat_count = 0
    if log_dir.exists():
        chat_count = len(list(log_dir.glob("*.jsonl")))

    # 审计条目数
    audit_count = 0
    try:
        from ...core.audit import query_summary
        result = query_summary()
        if result and isinstance(result, dict):
            audit_count = result.get("total", 0)
    except Exception:
        pass

    # 技能数
    skills_count = 0
    try:
        from pathlib import Path as P
        skills_dir = P("skills")
        if skills_dir.exists():
            skills_count = len([d for d in skills_dir.iterdir() if d.is_dir()])
    except Exception:
        pass

    return {
        "chat_count": chat_count,
        "providers_healthy": True,  # 后续接入 check 逻辑
        "skills_count": skills_count,
        "audit_count": audit_count,
    }
