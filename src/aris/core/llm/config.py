"""LLM 提供方配置：数据模型与 toml 加载。

提供方结构定义在 `config/providers.toml`（模板 `config/providers.example.toml`）：
每个提供方含名称、id、base_url、密钥环境变量名、超时、传输方式、
以及模型列表（统一 id / 请求名 / 支持格式）。

密钥（API key）不放 toml，通过 `api_key_env` 指定的环境变量从 .env 读取。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from loguru import logger

from .message import ApiFormat


class TransportKind(StrEnum):
    """LLM 请求传输方式（sdk 官方库 / httpx 手写）。"""

    SDK = "sdk"
    HTTPX = "httpx"


# ---- fallback / 超时默认值（真机实测可调的才写进 providers.toml）----
DEFAULT_TIMEOUT = 30.0          # 单次请求总超时（秒）
DEFAULT_CONNECT_TIMEOUT = 10.0  # 建连超时（秒），单独设避免慢连接拖垮总预算
DEFAULT_RETRY_COUNT = 1         # 可重试错误在同一提供方的重试次数（超出切下家）
DEFAULT_BACKOFF_BASE = 0.5      # 退避基数（秒），指数增长封顶 BACKOFF_MAX
DEFAULT_RACE_FALLBACK = True    # 降级后是否启用「本家 vs 备选」并发竞速恢复


@dataclass
class LLMModel:
    """统一模型定义（跨提供方共享 id，用于 fallback 匹配）。

    context_length：上下文窗口（tokens），供展示与后续自动选型。
    capabilities：能力关键词列表，约定 tools / reasoning / vision。
    thinking_default：默认思考模式开关；None=跟随提供方默认，
        False=默认关闭（请求体加 thinking:{"type":"disabled"}）。
    fallback_models：主模型失败后的降级目标（同一提供方内的模型 id 列表），
        由 engine 在同模型全灭后按顺序尝试（模型级降级）。
    """

    id: str
    name: str
    request_name: str
    formats: list[str] = field(default_factory=lambda: [ApiFormat.CHAT])
    context_length: int | None = None
    capabilities: list[str] = field(default_factory=list)
    thinking_default: bool | None = None
    fallback_models: list[str] = field(default_factory=list)


@dataclass
class LLMProvider:
    """一个 LLM 提供方。

    timeout：单次请求总超时（秒），覆盖读/写阶段。
    connect_timeout：建连（含 TLS）超时（秒），短一些让「连不上」快速失败。
    retry_count：可重试错误（限流/5xx/网络/超时）在本家的重试次数。
    backoff_base：退避基数（秒），指数退避上限见 engine.py 的 BACKOFF_MAX。
    race_fallback：降级后是否参与竞速恢复（付费/限配额提供方可关闭避免双倍消耗）。
    """

    id: str
    name: str
    base_url: str
    api_key_env: str
    timeout: float = DEFAULT_TIMEOUT
    transport: str = TransportKind.SDK  # sdk（openai SDK）/ httpx（手写请求）
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    retry_count: int = DEFAULT_RETRY_COUNT
    backoff_base: float = DEFAULT_BACKOFF_BASE
    race_fallback: bool = DEFAULT_RACE_FALLBACK
    models: list[LLMModel] = field(default_factory=list)

    def get_model(self, model_id: str) -> LLMModel | None:
        """按统一模型 id 查找模型，找不到返回 None。"""
        for m in self.models:
            if m.id == model_id:
                return m
        return None


class ProviderConfigError(FileNotFoundError):
    """config/providers.toml 缺失或格式错误。"""


@dataclass
class ProviderConfig:
    """提供方集合 + 尝试顺序 + 默认模型。"""

    providers: list[LLMProvider]
    order: list[str]
    default_model: str | None = None

    def ordered_providers(self) -> list[LLMProvider]:
        """按默认顺序返回提供方：order 中的 id 在前，其余按文件出现顺序补齐。"""
        by_id = {p.id: p for p in self.providers}
        ordered: list[LLMProvider] = []
        seen: set[str] = set()
        for pid in self.order:
            p = by_id.get(pid)
            if p is not None and pid not in seen:
                ordered.append(p)
                seen.add(pid)
        for p in self.providers:
            if p.id not in seen:
                ordered.append(p)
                seen.add(p.id)
        return ordered

    def candidates_for(self, model_id: str) -> list[LLMProvider]:
        """返回提供统一模型 id 的提供方（按尝试顺序）。"""
        return [p for p in self.ordered_providers() if p.get_model(model_id) is not None]

    def all_model_ids(self) -> list[str]:
        """返回全部提供方支持的统一模型 id（去重、按尝试顺序）。"""
        ids: list[str] = []
        for p in self.ordered_providers():
            for m in p.models:
                if m.id not in ids:
                    ids.append(m.id)
        return ids

    def resolve_default_model(self) -> str:
        """返回默认模型 id。

        配置了 default_model 且存在 → 直接返回；缺失/无效时兜底取
        order 第一个提供方的第一个模型，并记警告。
        """
        if self.default_model:
            if self.default_model in self.all_model_ids():
                return self.default_model
            logger.warning(
                f"default_model {self.default_model} 在任一提供方中不存在，"
                "兜底取第一个可用模型"
            )
        else:
            logger.warning("default_model 未配置，兜底取第一个可用模型")
        first = self.ordered_providers()
        if first and first[0].models:
            return first[0].models[0].id
        raise ProviderConfigError(
            "没有任何可用模型，请在 config/providers.toml 至少配置一个模型"
        )


def load_providers(path: str | Path) -> ProviderConfig:
    """从 toml 文件加载提供方配置。

    结构：
        default_provider_order = ["deepseek"]
        default_model = "deepseek-v4-flash"
        [[providers.provider]]
        id = "deepseek"
        timeout = 30
        connect_timeout = 10
        retry_count = 1
        backoff_base = 0.5
        race_fallback = true
        [[providers.provider.models]]
        id = "deepseek-v4-flash"
        fallback_models = ["deepseek-v3"]
        context_length = 1000000
        capabilities = ["tools", "reasoning"]
        thinking_default = false
    """
    p = Path(path)
    if not p.exists():
        raise ProviderConfigError(
            f"提供方配置文件不存在: {p}（可复制 config/providers.example.toml 为 config/providers.toml）"
        )
    with p.open("rb") as f:
        data = tomllib.load(f)

    entries = data.get("providers", {}).get("provider", [])
    providers: list[LLMProvider] = []
    seen_provider_ids: set[str] = set()
    for entry in entries:
        try:
            pid = entry["id"]
            if pid in seen_provider_ids:
                raise ProviderConfigError(
                    f"config/providers.toml 提供方 id 重复: {pid}"
                )
            seen_provider_ids.add(pid)

            models: list[LLMModel] = []
            seen_model_ids: set[str] = set()
            for m in entry.get("models", []):
                mid = m["id"]
                if mid in seen_model_ids:
                    raise ProviderConfigError(
                        f"提供方 {pid} 内模型 id 重复: {mid}"
                    )
                seen_model_ids.add(mid)
                models.append(
                    LLMModel(
                        id=mid,
                        name=m.get("name", mid),
                        request_name=m.get("request_name", mid),
                        formats=m.get("formats", [ApiFormat.CHAT]),
                        context_length=m.get("context_length"),
                        capabilities=list(m.get("capabilities", [])),
                        thinking_default=m.get("thinking_default"),
                        fallback_models=list(m.get("fallback_models", [])),
                    )
                )

            providers.append(
                LLMProvider(
                    id=pid,
                    name=entry.get("name", pid),
                    base_url=entry["base_url"],
                    api_key_env=entry.get("api_key_env", f"{pid.upper()}_API_KEY"),
                    timeout=float(entry.get("timeout", DEFAULT_TIMEOUT)),
                    transport=entry.get("transport", TransportKind.SDK),
                    connect_timeout=float(entry.get("connect_timeout", DEFAULT_CONNECT_TIMEOUT)),
                    retry_count=int(entry.get("retry_count", DEFAULT_RETRY_COUNT)),
                    backoff_base=float(entry.get("backoff_base", DEFAULT_BACKOFF_BASE)),
                    race_fallback=bool(entry.get("race_fallback", DEFAULT_RACE_FALLBACK)),
                    models=models,
                )
            )
        except KeyError as e:
            raise ProviderConfigError(
                f"config/providers.toml 提供方条目缺少必需字段: {e}"
            ) from e

    order = list(data.get("default_provider_order", []))
    default_model = data.get("default_model")
    return ProviderConfig(
        providers=providers, order=order, default_model=default_model
    )
