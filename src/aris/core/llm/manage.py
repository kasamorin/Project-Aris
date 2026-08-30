"""提供商管理服务——增删提供方/模型（注册 `llm.providers.*` 总线服务）。

供 WebUI（`aris web`）等常驻服务经 `core.call` 调用，模块间不走直连 import。
写回统一走 `fetch.write_providers`（先备份 .bak + tomli_w 结构化序列化）。
权限边界：本模块只做数据操作，路由层的输入校验（表单→URL 参数）由调用方负责，
这里仍做基本合法性校验（id 白名单 / base_url scheme），防越权误用。
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from aris.config import get_settings
from aris.core.bus import provide

from .config import LLMModel, LLMProvider, ProviderConfig, load_providers
from .fetch import write_providers

# 合法 id：小写字母、数字、连字符（fullmatch 防尾部换行绕过）
_ID_RE = re.compile(r"[a-z0-9-]+")


def _providers_path() -> str:
    """返回 providers.toml 路径（独立函数便于测试替换）。"""
    return get_settings().llm_providers_file


def _load() -> ProviderConfig:
    """从 providers.toml 加载配置。"""
    return load_providers(_providers_path())


def _save(cfg: ProviderConfig) -> None:
    """写回 providers.toml（write_providers 负责备份 + 序列化）。"""
    write_providers(_providers_path(), cfg)


def _valid_id(value: str) -> bool:
    """校验 id 合法性：小写字母/数字/连字符全匹配。"""
    return bool(_ID_RE.fullmatch(value))


def providers_load() -> ProviderConfig:
    """加载全部提供方配置（含 models 明细）。"""
    return _load()


def provider_add(pid: str, name: str, base_url: str, api_key_env: str) -> bool:
    """添加新提供方；id 已存在或参数非法时返回 False 不写盘。"""
    if not _valid_id(pid):
        return False
    scheme = urlparse(base_url).scheme
    if scheme not in ("http", "https"):
        return False
    cfg = _load()
    if any(p.id == pid for p in cfg.providers):
        return False
    cfg.providers.append(
        LLMProvider(id=pid, name=name, base_url=base_url, api_key_env=api_key_env)
    )
    _save(cfg)
    return True


def provider_delete(pid: str) -> None:
    """删除提供方（连同其在默认顺序中的位置）。"""
    cfg = _load()
    cfg.providers = [p for p in cfg.providers if p.id != pid]
    cfg.order = [o for o in cfg.order if o != pid]
    _save(cfg)


def model_add(pid: str, model_id: str, model_name: str, context_length: int) -> bool:
    """给指定提供方添加模型；model id 全局重复或参数非法返回 False。"""
    if not _valid_id(pid) or not _valid_id(model_id):
        return False
    cfg = _load()
    provider = next((p for p in cfg.providers if p.id == pid), None)
    if provider is None:
        return False
    if any(m.id == model_id for p in cfg.providers for m in p.models):
        return False
    provider.models.append(
        LLMModel(
            id=model_id,
            name=model_name or model_id,
            request_name=model_id,
            formats=["chat"],
            context_length=context_length or None,
        )
    )
    _save(cfg)
    return True


def model_delete(pid: str, model_id: str) -> None:
    """从指定提供方删除模型（只动该提供方自己的 models 表）。"""
    cfg = _load()
    provider = next((p for p in cfg.providers if p.id == pid), None)
    if provider is None:
        return
    provider.models = [m for m in provider.models if m.id != model_id]
    _save(cfg)


# ---- 总线服务注册 ----
provide("llm.providers.load", providers_load)
provide("llm.providers.add", provider_add)
provide("llm.providers.delete", provider_delete)
provide("llm.providers.model_add", model_add)
provide("llm.providers.model_delete", model_delete)