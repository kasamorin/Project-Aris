"""提供商管理路由——提供方增删、模型列表、fetch 审核、退休管理。"""

from __future__ import annotations

import os
import re
from urllib.parse import quote

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from loguru import logger

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
    _add_provider(id, name or id, base_url, api_key_env or f"{id.upper()}_API_KEY")
    return RedirectResponse(url=f"/providers?selected={quote(id)}", status_code=303)


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
    return RedirectResponse(url=f"/providers?selected={quote(pid)}", status_code=303)


@router.post("/providers/{pid}/delete-model", response_model=None)
async def provider_delete_model(
    pid: str,
    model_id: str = Form(...),
) -> RedirectResponse:
    """从提供方删除模型。"""
    _delete_model(pid, model_id)
    return RedirectResponse(url=f"/providers?selected={quote(pid)}", status_code=303)


@router.post("/providers/retired/{model}/delete", response_model=None)
async def retired_delete(model: str) -> RedirectResponse:
    """删除退休模型记录。"""
    _delete_retired(model)
    return RedirectResponse(url="/providers?tab=retired", status_code=303)


@router.get("/providers/{pid}/fetch", response_class=HTMLResponse)
async def provider_fetch_page(
    request: Request,
    pid: str,
) -> HTMLResponse:
    """fetch 审核页面：拉取端点模型 → 对比 → 勾选 → 写回。"""
    result = _do_fetch(pid)
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
    _apply_fetch(pid, selected)
    return RedirectResponse(url=f"/providers?selected={quote(pid)}", status_code=303)


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
    except Exception as e:
        # 外围展示功能：宽容降级，但必须留下排查线索
        logger.warning(f"加载提供方列表失败: {e}")
        return []


def _load_retired() -> list[dict]:
    """加载退休模型列表。"""
    try:
        from ...core.llm.fetch import load_retired
        entries = load_retired()
        return [{"model": e.model, "provider": e.provider, "first_missing": e.first_missing} for e in entries]
    except Exception:
        return []


def _do_fetch(pid: str) -> dict:
    """执行 fetch：拉取端点模型 → 对比 → 返回 diff。"""
    try:
        from ...core.llm import load_providers
        from ...core.llm.fetch import fetch_provider_models, load_retired, modelsdev_load, plan_sync
        from ...config import get_settings
        settings = get_settings()
        providers = load_providers(settings.llm_providers_file)

        # 找到目标提供方
        provider = None
        for p in providers.providers:
            if p.id == pid:
                provider = p
                break
        if provider is None:
            return {"error": f"提供方 {pid} 不存在"}

        # 拉取端点模型
        endpoint_ids = fetch_provider_models(provider)

        # 加载退休记录和 models.dev
        retired = load_retired()
        modelsdev = modelsdev_load(settings.data_dir)

        # 生成同步计划
        plan = plan_sync(provider, endpoint_ids, retired, modelsdev)

        return {
            "provider_name": provider.name,
            "added": [{"id": c.id, "name": c.name, "context": f"{c.context_length // 1000}K" if c.context_length else "-"} for c in plan.candidates],
            "kept": plan.diff.kept,
            "missing": plan.diff.missing,
            "restored": plan.retire.restored,
            "retired_now": [e.model for e in plan.retire.retired_now],
        }
    except Exception as e:
        return {"error": str(e)}


def _apply_fetch(pid: str, selected: list[str]) -> None:
    """应用 fetch 结果。"""
    try:
        from ...core.llm import load_providers
        from ...core.llm.fetch import (
            fetch_provider_models, load_retired, modelsdev_load,
            plan_sync, apply_sync, retired_file_path,
        )
        from ...config import get_settings
        settings = get_settings()
        providers = load_providers(settings.llm_providers_file)

        provider = None
        for p in providers.providers:
            if p.id == pid:
                provider = p
                break
        if provider is None:
            return

        endpoint_ids = fetch_provider_models(provider)
        retired = load_retired()
        modelsdev = modelsdev_load(settings.data_dir)
        plan = plan_sync(provider, endpoint_ids, retired, modelsdev)

        apply_sync(
            plan,
            selected,
            cfg=providers,
            providers_path=settings.llm_providers_file,
            retired=retired,
            retired_path=retired_file_path(),
        )
    except Exception as e:
        logger.warning(f"应用 fetch 结果失败 (pid={pid}): {e}")


def _load_providers_toml(path: Path) -> dict:
    """读取 providers.toml 为字典（文件缺失时返回空骨架）。"""
    import tomllib

    if not path.exists():
        return {"providers": {"provider": []}}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _save_providers_toml(path: Path, data: dict) -> None:
    """把字典写回 providers.toml（tomli_w 结构化写入，杜绝 TOML 注入）。"""
    import tomli_w

    path.write_text(tomli_w.dumps(data), encoding="utf-8")


def _add_provider(pid: str, name: str, base_url: str, api_key_env: str) -> None:
    """添加新提供方到 providers.toml（id 重复时静默跳过）。"""
    from ...config import get_settings

    path = get_settings().llm_providers_file
    data = _load_providers_toml(path)
    providers = data.setdefault("providers", {}).setdefault("provider", [])
    if any(p.get("id") == pid for p in providers):
        return
    providers.append({
        "id": pid,
        "name": name,
        "base_url": base_url,
        "api_key_env": api_key_env,
    })
    _save_providers_toml(path, data)


def _delete_provider(pid: str) -> None:
    """从 providers.toml 删除提供方。"""
    from ...config import get_settings

    path = get_settings().llm_providers_file
    data = _load_providers_toml(path)
    providers = data.get("providers", {}).get("provider", [])
    data["providers"]["provider"] = [p for p in providers if p.get("id") != pid]
    _save_providers_toml(path, data)


def _add_model(pid: str, model_id: str, model_name: str, context_length: int) -> None:
    """添加模型到指定提供方（model id 全局重复时跳过，保持原语义）。"""
    from ...config import get_settings

    path = get_settings().llm_providers_file
    data = _load_providers_toml(path)
    providers = data.get("providers", {}).get("provider", [])

    # 全局查重：任何提供方下已有同 id 模型则跳过（与旧行为一致）
    for p in providers:
        if any(m.get("id") == model_id for m in p.get("models", [])):
            return

    target = next((p for p in providers if p.get("id") == pid), None)
    if target is None:
        return
    target.setdefault("models", []).append({
        "id": model_id,
        "name": model_name,
        "request_name": model_id,
        "formats": ["chat"],
        **({"context_length": context_length} if context_length else {}),
    })
    _save_providers_toml(path, data)


def _delete_model(pid: str, model_id: str) -> None:
    """从指定提供方删除模型（只动该提供方自己的 models 表）。"""
    from ...config import get_settings

    path = get_settings().llm_providers_file
    data = _load_providers_toml(path)
    providers = data.get("providers", {}).get("provider", [])

    target = next((p for p in providers if p.get("id") == pid), None)
    if target is None or "models" not in target:
        return
    target["models"] = [m for m in target["models"] if m.get("id") != model_id]
    _save_providers_toml(path, data)


def _delete_retired(model: str) -> None:
    """删除退休模型记录。"""
    try:
        from ...core.llm.fetch import load_retired, save_retired
        entries = load_retired()
        kept = [e for e in entries if e.model != model]
        save_retired(kept)
    except Exception as e:
        logger.warning(f"删除退休记录失败 (model={model}): {e}")
