"""/models 同步核心逻辑：拉取 + 对比 + models.dev enrichment + 写回 + 退休巡检。

设计见 `developDoc/LLM-PROVIDER-MGMT.md` 阶段二。本模块保持纯逻辑
（不依赖 prompt_toolkit），交互勾选 UI 在 cli.py 组装。

同步规则（白名单语义）：
- 云有本地无 → 添加候选（默认不自动加，由用户勾选；非 TTY --write 全加）
- 两边都有 → 保留
- 本地有云无 → 移入退休文件（config/retired_models.toml），从配置移除
- 退休巡检：回归端点 → 自动恢复；超宽限期（默认 30 天）→ 永久删除
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx
import tomllib
import tomli_w
from loguru import logger

from aris.cfgtoml import config_dir

from .config import LLMModel, LLMProvider, ProviderConfig
from .errors import AuthError, LLMError
from .message import ApiFormat

# models.dev 数据源与缓存策略
MODELSDEV_URL = "https://models.dev/api.json"
MODELSDEV_CACHE_TTL = 7 * 24 * 3600  # 秒

# 退休宽限期：超过该天数未恢复且未手动删除则永久删除
RETIRED_GRACE_DAYS = 30


# ---------- 拉取 /models ----------


def fetch_provider_models(provider: LLMProvider, timeout: float = 20.0) -> list[str]:
    """GET {base_url}/models，返回模型 id 列表（标准 OpenAI 格式）。

    有 key 则带鉴权请求；无 key 先匿名尝试，401 时给明确提示（如 DeepSeek）。
    失败抛 LLMError / AuthError，不静默。
    """
    url = f"{provider.base_url.rstrip('/')}/models"
    headers = {"Accept": "application/json"}
    key = os.environ.get(provider.api_key_env)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        resp = httpx.get(url, headers=headers, timeout=timeout)
    except httpx.HTTPError as e:
        raise LLMError(f"拉取模型列表失败（网络错误）: {e}", provider_id=provider.id) from e
    if resp.status_code == 401:
        raise AuthError(
            f"/models 需要鉴权，请在 .env 设置 {provider.api_key_env}",
            provider_id=provider.id,
        )
    if resp.status_code != 200:
        raise LLMError(
            f"/models 返回 HTTP {resp.status_code}: {resp.text[:200]}",
            provider_id=provider.id,
        )
    try:
        data = resp.json()
    except ValueError as e:
        raise LLMError(f"/models 响应不是合法 JSON: {e}", provider_id=provider.id) from e
    return [m["id"] for m in data.get("data", []) if m.get("id")]


# ---------- models.dev enrichment ----------


def modelsdev_load(data_dir: Path, *, refresh: bool = False) -> dict:
    """加载 models.dev api.json（带 7 天缓存）。

    refresh=True 强制重新下载。下载/解析失败时返回空 dict（enrichment 宽容降级，
    元数据留空不影响同步主流程）。
    """
    path = data_dir / "models-dev.json"
    if not refresh and path.exists():
        age = _dt.datetime.now().timestamp() - path.stat().st_mtime
        if age < MODELSDEV_CACHE_TTL:
            try:
                with path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except (ValueError, OSError):
                logger.warning("models.dev 缓存损坏，重新下载")
    try:
        resp = httpx.get(MODELSDEV_URL, timeout=60)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.error(f"models.dev 下载失败: {e}")
        return {}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f)
        logger.info(f"models.dev 数据已缓存到 {path}")
    except OSError as e:
        logger.warning(f"models.dev 缓存写盘失败: {e}")
    return data


def enrich_model(provider_id: str, model_id: str, modelsdev: dict) -> LLMModel:
    """查 models.dev 生成带元数据的 LLMModel；未收录时 name/request_name=id。

    字段映射：name → name；limit.context → context_length；
    tool_call / reasoning / modalities 图像 → capabilities。
    """
    meta = modelsdev.get(provider_id, {}).get("models", {}).get(model_id) or {}
    name = meta.get("name") or model_id
    capabilities: list[str] = []
    if meta.get("tool_call"):
        capabilities.append("tools")
    if meta.get("reasoning"):
        capabilities.append("reasoning")
    input_modalities = (meta.get("modalities") or {}).get("input") or []
    if any("image" in str(m).lower() for m in input_modalities):
        capabilities.append("vision")
    context = None
    limit = meta.get("limit") or {}
    if limit.get("context"):
        context = int(limit["context"])
    return LLMModel(
        id=model_id,
        name=name,
        request_name=model_id,
        formats=[ApiFormat.CHAT],
        context_length=context,
        capabilities=capabilities,
    )


# ---------- 三方对比 ----------


@dataclass
class SyncDiff:
    """端点 vs 本地配置的对比结果。"""

    added: list[str]    # 云有本地无（添加候选）
    kept: list[str]     # 两边都有
    missing: list[str]  # 本地有云无（退休候选）


def compute_diff(provider: LLMProvider, endpoint_ids: list[str]) -> SyncDiff:
    """按白名单语义对比：仅端点新模型进入候选，缺失模型进入退休候选。"""
    local = {m.id for m in provider.models}
    ep = set(endpoint_ids)
    return SyncDiff(
        added=[mid for mid in endpoint_ids if mid not in local],
        kept=[mid for mid in endpoint_ids if mid in local],
        missing=[m.id for m in provider.models if m.id not in ep],
    )


# ---------- 退休机制 ----------


@dataclass
class RetiredEntry:
    """一条退休记录：模型曾配置但已从端点失联，进入宽限期。"""

    provider: str
    model: str
    first_missing: str  # ISO 日期，宽限期起算


def retired_file_path() -> Path:
    """退休文件位置（config/retired_models.toml，机器维护）。"""
    return config_dir() / "retired_models.toml"


def load_retired(path: Path | None = None) -> list[RetiredEntry]:
    """读取退休记录；文件缺失返回空列表。"""
    p = path or retired_file_path()
    if not p.exists():
        return []
    try:
        with p.open("rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        logger.warning(f"退休文件解析失败（{e}），按空处理")
        return []
    return [
        RetiredEntry(
            provider=e.get("provider", ""),
            model=e["model"],
            first_missing=str(e.get("first_missing", "")),
        )
        for e in data.get("retired", [])
    ]


def save_retired(entries: list[RetiredEntry], path: Path | None = None) -> None:
    """写退休记录（按 provider+model 排序，保证幂等）。"""
    p = path or retired_file_path()
    data = {
        "retired": [
            asdict(e) for e in sorted(entries, key=lambda e: (e.provider, e.model))
        ]
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("wb") as f:
        tomli_w.dump(data, f)


@dataclass
class RetireResult:
    """退休巡检结果。"""

    restored: list[str]          # 回归端点（从退休移除，自动恢复）
    expired: list[RetiredEntry]  # 超宽限期（永久删除）
    active: list[RetiredEntry]   # 宽限期内（保留待下次）
    retired_now: list[RetiredEntry]  # 本次新退休（缺失 → 退休文件）


def reconcile_retired(
    provider: LLMProvider,
    endpoint_ids: list[str],
    retired: list[RetiredEntry],
    *,
    today: _dt.date | None = None,
    grace_days: int = RETIRED_GRACE_DAYS,
) -> RetireResult:
    """对单个提供方的退休记录巡检：回归恢复 / 超期删除 / 新退休入列。"""
    today = today or _dt.date.today()
    ep = set(endpoint_ids)
    local = {m.id for m in provider.models}
    restored: list[str] = []
    expired: list[RetiredEntry] = []
    active: list[RetiredEntry] = []
    for e in retired:
        if e.provider != provider.id:
            active.append(e)  # 其他提供方的退休项不动
            continue
        if e.model in ep:
            restored.append(e.model)  # 回归端点，自动恢复
            continue
        try:
            missing_since = _dt.date.fromisoformat(e.first_missing)
        except ValueError:
            missing_since = today
        if (today - missing_since).days > grace_days:
            expired.append(e)
        else:
            active.append(e)
    # 本地有云无 → 新退休（避免与已退休重复）
    retired_ids = {e.model for e in active}
    retired_now = [
        RetiredEntry(provider=provider.id, model=mid, first_missing=today.isoformat())
        for mid in sorted(local - ep)
        if mid not in retired_ids
    ]
    return RetireResult(
        restored=sorted(restored),
        expired=expired,
        active=active,
        retired_now=retired_now,
    )


# ---------- 同步计划与落盘 ----------


@dataclass
class SyncPlan:
    """一次 fetch 的完整同步计划（不落盘，供 UI/非 TTY 决定后 apply）。"""

    provider: LLMProvider
    endpoint_ids: list[str]
    diff: SyncDiff
    retire: RetireResult
    candidates: list[LLMModel]  # 添加候选 = 纯新增 + 回归恢复，带 enrichment 元数据


def plan_sync(
    provider: LLMProvider,
    endpoint_ids: list[str],
    retired: list[RetiredEntry],
    modelsdev: dict,
    *,
    today: _dt.date | None = None,
    grace_days: int = RETIRED_GRACE_DAYS,
) -> SyncPlan:
    """生成同步计划：对比 + 退休巡检 + 候选 enrichment。"""
    diff = compute_diff(provider, endpoint_ids)
    retire = reconcile_retired(
        provider, endpoint_ids, retired, today=today, grace_days=grace_days
    )
    to_enrich = sorted(set(diff.added) | set(retire.restored))
    candidates = [enrich_model(provider.id, mid, modelsdev) for mid in to_enrich]
    return SyncPlan(
        provider=provider,
        endpoint_ids=endpoint_ids,
        diff=diff,
        retire=retire,
        candidates=candidates,
    )


def config_to_dict(cfg: ProviderConfig) -> dict:
    """ProviderConfig → dict（供 tomli_w 序列化；None 值跳过）。"""
    providers: list[dict] = []
    for p in cfg.providers:
        models: list[dict] = []
        for m in p.models:
            d: dict = {
                "id": m.id,
                "name": m.name,
                "request_name": m.request_name,
                "formats": list(m.formats),
            }
            if m.context_length is not None:
                d["context_length"] = m.context_length
            if m.capabilities:
                d["capabilities"] = list(m.capabilities)
            if m.thinking_default is not None:
                d["thinking_default"] = m.thinking_default
            models.append(d)
        pd: dict = {
            "id": p.id,
            "name": p.name,
            "base_url": p.base_url,
            "api_key_env": p.api_key_env,
            "models": models,
        }
        if p.timeout != 30.0:
            pd["timeout"] = p.timeout
        if p.transport != "sdk":
            pd["transport"] = p.transport
        providers.append(pd)
    data: dict = {
        "default_provider_order": list(cfg.order),
        "providers": {"provider": providers},
    }
    if cfg.default_model:
        data["default_model"] = cfg.default_model
    return data


def write_providers(path: str | Path, cfg: ProviderConfig) -> None:
    """写回 providers.toml；写前备份为同目录 <原名>.bak 文件。"""
    p = Path(path)
    if p.exists():
        shutil.copy2(p, Path(f"{p}.bak"))
    with p.open("wb") as f:
        tomli_w.dump(config_to_dict(cfg), f)


def apply_sync(
    plan: SyncPlan,
    selected: list[str],
    *,
    cfg: ProviderConfig,
    providers_path: str | Path,
    retired: list[RetiredEntry],
    keep: list[str] | None = None,
    retired_path: Path | None = None,
) -> None:
    """把勾选结果落盘：改 providers.toml + 更新退休文件。

    selected：勾选的候选模型 id（含回归恢复）。
    keep：本地有云无但用户要求保留的模型 id（不退休）。
    """
    provider = plan.provider
    keep = keep or []

    # 1. 移除缺失模型（除 keep 外 → 退休）
    provider.models = [m for m in provider.models if m.id not in plan.diff.missing or m.id in keep]

    # 2. 添加勾选候选（含回归恢复；已存在则跳过）
    selected_set = set(selected)
    for m in plan.candidates:
        if m.id in selected_set and provider.get_model(m.id) is None:
            provider.models.append(m)

    # 3. 新退休记录 + 保留未到期项（回归与过期项已从结果中排除；
    #    keep 的模型不进退休列表）
    keep_ids = set(keep)
    new_entries = list(plan.retire.active) + [
        e for e in plan.retire.retired_now if e.model not in keep_ids
    ]
    save_retired(new_entries, path=retired_path)

    # 4. 写回 providers.toml（含备份）
    write_providers(providers_path, cfg)
