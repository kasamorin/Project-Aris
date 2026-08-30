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
    """收集仪表盘统计数据（外围展示功能：失败宽容降级，不中断页面）。"""
    try:
        return _gather_stats_impl()
    except Exception as e:
        from loguru import logger
        logger.warning(f"仪表盘统计收集失败: {e}")
        return {
            "chat_count": 0,
            "providers_healthy": False,
            "skills_count": 0,
            "audit_count": 0,
        }


def _gather_stats_impl() -> dict:
    """统计实际聚合逻辑（被 _gather_stats 容错包裹）。"""
    import datetime
    import os

    from aris.core import call
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
    summary = call("audit.summary") or {}
    if isinstance(summary, dict):
        audit_count = summary.get("total", 0)

    # 技能数（总线 skills.list 返回完整列表，与其展示口径一致）
    skills_count = len(call("skills.list") or [])

    # 提供商健康状态（任一提供方缺密钥即视为不健康）
    providers_healthy = True
    cfg = call("llm.providers.load")
    if cfg is None:
        providers_healthy = False
    else:
        for p in cfg.ordered_providers():
            if not os.environ.get(p.api_key_env):
                providers_healthy = False
                break

    return {
        "chat_count": chat_count,
        "providers_healthy": providers_healthy,
        "skills_count": skills_count,
        "audit_count": audit_count,
    }
