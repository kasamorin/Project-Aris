"""提供商管理路由——提供方增删、模型列表、fetch 审核、退休管理。"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from ..templates import render

router = APIRouter()


@router.get("/providers", response_class=HTMLResponse)
async def providers_page(
    request: Request,
    selected: str | None = Query(None),
) -> HTMLResponse:
    """提供商管理页面。"""
    providers = _load_providers()
    return render(request, "providers.html", {
        "active_page": "providers",
        "providers": providers,
        "selected": selected,
    })


def _load_providers() -> list[dict]:
    """加载提供方列表。"""
    import os
    try:
        from ...core.llm import load_providers
        from ...config import get_settings
        settings = get_settings()
        providers = load_providers(settings.llm_providers_file)
        result = []
        for p in providers.ordered_providers():
            key_ok = bool(os.environ.get(p.api_key_env))
            models = []
            for m in p.models:
                caps = ", ".join(m.capabilities) if m.capabilities else "-"
                ctx = f"{m.context_length // 1000}K" if m.context_length else "-"
                models.append({
                    "id": m.id,
                    "name": m.name,
                    "context": ctx,
                    "capabilities": caps,
                    "thinking_default": str(m.thinking_default) if m.thinking_default is not None else "跟随",
                })
            result.append({
                "id": p.id,
                "name": p.name,
                "base_url": p.base_url,
                "key_ok": key_ok,
                "key_env": p.api_key_env,
                "model_count": len(p.models),
                "models": models,
            })
        return result
    except Exception:
        return []
