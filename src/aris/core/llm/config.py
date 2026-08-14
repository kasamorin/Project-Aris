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


@dataclass
class LLMModel:
    """统一模型定义（跨提供方共享 id，用于 fallback 匹配）。

    context_length：上下文窗口（tokens），供展示与后续自动选型。
    capabilities：能力关键词列表，约定 tools / reasoning / vision。
    thinking_default：默认思考模式开关；None=跟随提供方默认，
        False=默认关闭（请求体加 thinking:{"type":"disabled"}）。
    """

    id: str
    name: str
    request_name: str
    formats: list[str] = field(default_factory=lambda: [ApiFormat.CHAT])
    context_length: int | None = None
    capabilities: list[str] = field(default_factory=list)
    thinking_default: bool | None = None


@dataclass
class LLMProvider:
    """一个 LLM 提供方。"""

    id: str
    name: str
    base_url: str
    api_key_env: str
    timeout: float = 30.0
    transport: str = TransportKind.SDK  # sdk（openai SDK）/ httpx（手写请求）
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
        ...
        [[providers.provider.models]]
        id = "deepseek-v4-flash"
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
                    )
                )

            providers.append(
                LLMProvider(
                    id=pid,
                    name=entry.get("name", pid),
                    base_url=entry["base_url"],
                    api_key_env=entry.get("api_key_env", f"{pid.upper()}_API_KEY"),
                    timeout=float(entry.get("timeout", 30.0)),
                    transport=entry.get("transport", TransportKind.SDK),
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
