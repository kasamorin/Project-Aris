"""提供商管理路由——提供方增删、模型列表、fetch 审核、退休管理。"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..templates import render

router = APIRouter()


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
    import re
    if not re.match(r"^[a-z0-9-]+$", id):
        return RedirectResponse(url="/providers?error=ID格式错误", status_code=303)
    _add_provider(id, name or id, base_url, api_key_env or f"{id.upper()}_API_KEY")
    return RedirectResponse(url=f"/providers?selected={id}", status_code=303)


@router.post("/providers/{pid}/delete", response_model=None)
async def provider_delete(pid: str) -> RedirectResponse:
    """删除提供方。"""
    _delete_provider(pid)
    return RedirectResponse(url="/providers", status_code=303)


@router.post("/providers/{pid}/add-model", response_model=None)
async def provider_add_model(
    pid: str,
    model_id: str = Form(...),
    model_name: str = Form(""),
    context_length: int = Form(0),
) -> RedirectResponse:
    """添加模型到提供方。"""
    _add_model(pid, model_id, model_name or model_id, context_length)
    return RedirectResponse(url=f"/providers?selected={pid}", status_code=303)


@router.post("/providers/{pid}/delete-model", response_model=None)
async def provider_delete_model(
    pid: str,
    model_id: str = Form(...),
) -> RedirectResponse:
    """从提供方删除模型。"""
    _delete_model(pid, model_id)
    return RedirectResponse(url=f"/providers?selected={pid}", status_code=303)


@router.post("/providers/retired/{model}/delete", response_model=None)
async def retired_delete(model: str) -> RedirectResponse:
    """删除退休模型记录。"""
    _delete_retired(model)
    return RedirectResponse(url="/providers?tab=retired", status_code=303)


def _load_providers() -> list[dict]:
    """加载提供方列表。"""
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


def _load_retired() -> list[dict]:
    """加载退休模型列表。"""
    try:
        from ...core.llm.fetch import load_retired
        entries = load_retired()
        return [{"model": e.model, "provider": e.provider, "first_missing": e.first_missing} for e in entries]
    except Exception:
        return []


def _add_provider(pid: str, name: str, base_url: str, api_key_env: str) -> None:
    """添加新提供方到 providers.toml。"""
    from ...config import get_settings
    settings = get_settings()
    path = settings.llm_providers_file

    content = path.read_text(encoding="utf-8") if path.exists() else ""

    # 检查是否已存在
    if f'id = "{pid}"' in content:
        return

    # 追加新提供方
    new_provider = f'''
[[providers.provider]]
id = "{pid}"
name = "{name}"
base_url = "{base_url}"
api_key_env = "{api_key_env}"
'''
    content += new_provider
    path.write_text(content, encoding="utf-8")


def _delete_provider(pid: str) -> None:
    """从 providers.toml 删除提供方。"""
    from ...config import get_settings
    settings = get_settings()
    path = settings.llm_providers_file
    if not path.exists():
        return

    content = path.read_text(encoding="utf-8")
    lines = content.split("\n")
    result = []
    skip = False
    for line in lines:
        if line.strip() == f'id = "{pid}"':
            skip = True
            continue
        if skip and line.strip().startswith("[[providers.provider]]"):
            skip = False
        if not skip:
            result.append(line)

    path.write_text("\n".join(result), encoding="utf-8")


def _add_model(pid: str, model_id: str, model_name: str, context_length: int) -> None:
    """添加模型到提供方。"""
    from ...config import get_settings
    settings = get_settings()
    path = settings.llm_providers_file
    if not path.exists():
        return

    content = path.read_text(encoding="utf-8")

    # 检查模型是否已存在
    if f'id = "{model_id}"' in content:
        return

    # 找到提供方位置，在其 models 列表末尾追加
    lines = content.split("\n")
    result = []
    in_provider = False
    inserted = False
    for i, line in enumerate(lines):
        result.append(line)
        if f'id = "{pid}"' in line:
            in_provider = True
        if in_provider and not inserted:
            # 找到该提供方的最后一个 model 块后插入
            if i + 1 < len(lines) and not lines[i + 1].strip().startswith("[[providers"):
                if line.strip().startswith("thinking_default") or line.strip().startswith("capabilities"):
                    new_model = f'''
[[providers.provider.models]]
id = "{model_id}"
name = "{model_name}"
request_name = "{model_id}"
formats = ["chat"]
context_length = {context_length}
'''
                    result.append(new_model)
                    inserted = True

    path.write_text("\n".join(result), encoding="utf-8")


def _delete_model(pid: str, model_id: str) -> None:
    """从提供方删除模型。"""
    from ...config import get_settings
    settings = get_settings()
    path = settings.llm_providers_file
    if not path.exists():
        return

    content = path.read_text(encoding="utf-8")
    lines = content.split("\n")
    result = []
    skip = False
    for line in lines:
        if line.strip() == f'id = "{model_id}"':
            skip = True
            continue
        if skip and (line.strip().startswith("[[providers") or line.strip().startswith("id =")):
            skip = False
        if not skip:
            result.append(line)

    path.write_text("\n".join(result), encoding="utf-8")


def _delete_retired(model: str) -> None:
    """删除退休模型记录。"""
    try:
        from ...core.llm.fetch import load_retired, save_retired
        entries = load_retired()
        kept = [e for e in entries if e.model != model]
        save_retired(kept)
    except Exception:
        pass
