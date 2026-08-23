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
    import datetime
    import os
    from pathlib import Path
    from ...config import get_settings

    settings = get_settings()

    # 今日对话数（统计 jsonl 文件）
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
    skills_dir = Path("skills")
    if skills_dir.exists():
        skills_count = len([d for d in skills_dir.iterdir() if d.is_dir()])

    # 提供商健康状态
    providers_healthy = True
    try:
        from ...core.llm import load_providers
        providers = load_providers(settings.llm_providers_file)
        for p in providers.ordered_providers():
            if not os.environ.get(p.api_key_env):
                providers_healthy = False
                break
    except Exception:
        providers_healthy = False

    return {
        "chat_count": chat_count,
        "providers_healthy": providers_healthy,
        "skills_count": skills_count,
        "audit_count": audit_count,
    }
