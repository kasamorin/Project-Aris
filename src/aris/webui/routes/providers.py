"""提供商管理路由——提供方增删、模型列表、fetch 审核、退休管理。

跨模块能力一律经 `core.call` 从总线获取（llm.* 服务注册在
core/llm/manage.py 与 core/llm/fetch.py），不直接 import core.llm。
"""

from __future__ import annotations

import os
import re
from urllib.parse import quote

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from aris.core import call
from ..templates import render

router = APIRouter()

# 合法提供方 id：小写字母、数字、连字符（fullmatch 防尾部换行绕过）
_PID_RE = re.compile(r"[a-z0-9-]+")


@router.get("/providers", response_class=HTMLResponse)
async def providers_page(
    request: Request,
    selected: str | None = Query(None),
    tab: str = Query("models"),
) -> HTMLResponse:
    """提供商管理页面。"""
    providers = _load_providers()
    retired = _load_retired()
    return render(request, "providers.html", {
        "active_page": "providers",
        "providers": providers,
        "selected": selected,
        "tab": tab,
        "retired": retired,
    })


@router.post("/providers/add", response_model=None)
async def provider_add(
    request: Request,
    id: str = Form(...),
    name: str = Form(""),
    base_url: str = Form(...),
    api_key_env: str = Form(""),
) -> RedirectResponse:
    """添加新提供方。"""
    if not _PID_RE.fullmatch(id):
        return RedirectResponse(url="/providers?error=ID%E6%A0%BC%E5%BC%8F%E9%94%99%E8%AF%AF", status_code=303)
    ok = call("llm.providers.add", id, name or id, base_url, api_key_env or f"{id.upper()}_API_KEY")
    if ok:
        return RedirectResponse(url=f"/providers?selected={quote(id)}", status_code=303)
    return RedirectResponse(url="/providers?error=%E6%B7%BB%E5%8A%A0%E5%A4%B1%E8%B4%A5", status_code=303)


@router.post("/providers/{pid}/delete", response_model=None)
async def provider_delete(pid: str) -> RedirectResponse:
    """删除提供方。"""
    call("llm.providers.delete", pid)
    return RedirectResponse(url="/providers", status_code=303)


@router.post("/providers/{pid}/add-model", response_model=None)
async def provider_add_model(
    pid: str,
    model_id: str = Form(...),
    model_name: str = Form(""),
    context_length: int = Form(0),
) -> RedirectResponse:
    """添加模型到提供方。"""
    call("llm.providers.model_add", pid, model_id, model_name, context_length)
    return RedirectResponse(url=f"/providers?selected={quote(pid)}", status_code=303)


@router.post("/providers/{pid}/delete-model", response_model=None)
async def provider_delete_model(
    pid: str,
    model_id: str = Form(...),
) -> RedirectResponse:
    """从提供方删除模型。"""
    call("llm.providers.model_delete", pid, model_id)
    return RedirectResponse(url=f"/providers?selected={quote(pid)}", status_code=303)


@router.post("/providers/retired/{model}/delete", response_model=None)
async def retired_delete(model: str) -> RedirectResponse:
    """删除退休模型记录。"""
    call("llm.retired.delete", model)
    return RedirectResponse(url="/providers?tab=retired", status_code=303)


@router.get("/providers/{pid}/fetch", response_class=HTMLResponse)
async def provider_fetch_page(
    request: Request,
    pid: str,
) -> HTMLResponse:
    """fetch 审核页面：拉取端点模型 → 对比 → 勾选 → 写回。"""
    result = call("llm.fetch.plan", pid) or {"error": f"提供方 {pid} 不存在"}
    if "error" in result:
        return render(request, "providers.html", {
            "active_page": "providers",
            "providers": _load_providers(),
            "selected": pid,
            "tab": "models",
            "error": result["error"],
        })
    return render(request, "fetch.html", {
        "active_page": "providers",
        "pid": pid,
        "provider_name": result["provider_name"],
        "added": result["added"],
        "kept": result["kept"],
        "missing": result["missing"],
        "restored": result["restored"],
        "retired_now": result["retired_now"],
    })


@router.post("/providers/{pid}/fetch/apply", response_model=None)
async def provider_fetch_apply(
    pid: str,
    selected: list[str] = Form([]),
) -> RedirectResponse:
    """应用 fetch 结果：勾选的候选写入 providers.toml。"""
    call("llm.fetch.apply", pid, selected)
    return RedirectResponse(url=f"/providers?selected={quote(pid)}", status_code=303)


def _load_providers() -> list[dict]:
    """加载提供方列表（展示用；密钥状态只查环境变量是否存在，不读值）。

    外围展示功能：配置文件缺/损坏时宽容降级为空列表，不中断页面。
    """
    try:
        cfg = call("llm.providers.load")
    except Exception as e:
        from loguru import logger
        logger.warning(f"提供商列表加载失败，按空列表展示: {e}")
        return []
    if cfg is None:
        return []
    result = []
    for p in cfg.ordered_providers():
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


def _load_retired() -> list[dict]:
    """加载退休模型列表。"""
    entries = call("llm.retired.list")
    if entries is None:
        return []
    return [{"model": e.model, "provider": e.provider, "first_missing": e.first_missing} for e in entries]