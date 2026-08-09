"""LLM 提供方配置：数据模型与 toml 加载。

提供方结构定义在 `providers.toml`（模板 `providers.example.toml`）：
每个提供方含名称、id、base_url、密钥环境变量名、超时、传输方式、
以及模型列表（统一 id / 请求名 / 支持格式）。

密钥（API key）不放 toml，通过 `api_key_env` 指定的环境变量从 .env 读取。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LLMModel:
    """统一模型定义（跨提供方共享 id，用于 fallback 匹配）。"""

    id: str
    name: str
    request_name: str
    formats: list[str] = field(default_factory=lambda: ["chat"])


@dataclass
class LLMProvider:
    """一个 LLM 提供方。"""

    id: str
    name: str
    base_url: str
    api_key_env: str
    timeout: float = 30.0
    transport: str = "sdk"  # sdk（openai SDK）/ httpx（手写请求）
    models: list[LLMModel] = field(default_factory=list)

    def get_model(self, model_id: str) -> LLMModel | None:
        """按统一模型 id 查找模型，找不到返回 None。"""
        for m in self.models:
            if m.id == model_id:
                return m
        return None


class ProviderConfigError(FileNotFoundError):
    """providers.toml 缺失或格式错误。"""


@dataclass
class ProviderConfig:
    """提供方集合 + 尝试顺序。"""

    providers: list[LLMProvider]
    order: list[str]

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


def load_providers(path: str | Path) -> ProviderConfig:
    """从 toml 文件加载提供方配置。

    结构：
        default_provider_order = ["deepseek"]
        [[providers.provider]]
        id = "deepseek"
        ...
        [[providers.provider.models]]
        id = "deepseek-v4-flash"
    """
    p = Path(path)
    if not p.exists():
        raise ProviderConfigError(
            f"提供方配置文件不存在: {p}（可复制 providers.example.toml 为 providers.toml）"
        )
    with p.open("rb") as f:
        data = tomllib.load(f)

    entries = data.get("providers", {}).get("provider", [])
    providers: list[LLMProvider] = []
    for entry in entries:
        try:
            models = [
                LLMModel(
                    id=m["id"],
                    name=m.get("name", m["id"]),
                    request_name=m.get("request_name", m["id"]),
                    formats=m.get("formats", ["chat"]),
                )
                for m in entry.get("models", [])
            ]
            providers.append(
                LLMProvider(
                    id=entry["id"],
                    name=entry.get("name", entry["id"]),
                    base_url=entry["base_url"],
                    api_key_env=entry.get("api_key_env", f"{entry['id'].upper()}_API_KEY"),
                    timeout=float(entry.get("timeout", 30.0)),
                    transport=entry.get("transport", "sdk"),
                    models=models,
                )
            )
        except KeyError as e:
            raise ProviderConfigError(
                f"providers.toml 提供方条目缺少必需字段: {e}"
            ) from e

    order = list(data.get("default_provider_order", []))
    return ProviderConfig(providers=providers, order=order)
