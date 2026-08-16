"""内置工具：http_request —— 通用 HTTP 请求（走 core.http 服务）。

背景（2026-08-15）：参考 kelivo_fetch MCP 工具设计，补齐 web_open(id) 的
两个短板：① 无法直接打开对话中出现的 URL（只认搜索结果 id）；② 长文
一次截断无法续读。并支持发请求（POST 等），为 AstrBook 等外部能力提供
接口基础。

安全规则（写在工具描述里，模型须遵守；服务器侧用 host 级校验兜底）：
- 只能请求对话中已出现的 URL：用户提供 / web_search 返回 / 之前
  http_request 的结果。模型只要在回复里提过一次该域名即放行（固有边界，
  规则主要挡「凭空编造域名」）
- 不能访问需要认证的内容（登录墙 / 私有文档）
- 密钥不放请求头 / 请求体（走 .env / 模块配置）

设计：
- 走 core.call("http.request")，与 LLM 请求同理，可审计可复用
- GET + HTML：简化成紧凑 markdown（web_common.extract_page），
  max_length 限长、start_index 续读（缓存最近一次响应全文）
- 非 GET / 非 HTML：按原文返回（JSON API 等）
- raw=true：返回原始文本（HTML 源码）而非简化 markdown
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from loguru import logger

from aris.cfgtoml import load_config
from aris.core import call
from ..registry import ToolRegistry
from .web_common import extract_page


class HttpRequestResultType(StrEnum):
    """http_request 工具返回结果的外层标识。"""

    RESULT = "http_request_result"  # 请求成功
    ERROR = "http_request_error"    # 请求失败（宽容降级）


@dataclass
class HttpRequestConfig:
    """http_request 工具可调参数（config/search.toml）。"""

    http_request_max_chars: int = 4000      # 单次返回内容上限（字符）
    http_request_timeout_seconds: float = 20.0


_http_config = load_config(HttpRequestConfig(), "search.toml")

# 允许的 HTTP 方法白名单
_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

# 最近一次请求全文缓存（覆盖式，key=method|url|body，支持 start_index 续读）
_page_cache: dict[str, str] = {}


def _cache_key(method: str, url: str, body: str | None) -> str:
    """续读缓存的 key：方法 + URL + 请求体摘要（区分不同 POST 内容）。"""
    digest = hashlib.md5((body or "").encode()).hexdigest()[:8]
    return f"{method}|{url}|{digest}"


def _in_conversation(url: str, context: str | None) -> bool:
    """URL 或其 host 是否出现在对话文本中（host 级软校验）。

    模型只要在回复里提过一次该域名即可放行——这是 host 级校验的固有
    边界（2026-08-15 已确认保留规则），规则主要挡「凭空编造域名」。
    """
    if not context:
        return False
    if url in context:
        return True
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return bool(host) and host in context.lower()


def _do_request(
    *,
    url: str,
    method: str,
    headers: dict[str, str] | None,
    body: str | None,
    max_length: int,
    start_index: int,
    raw: bool,
    context: str | None,
) -> str:
    """执行一次 HTTP 请求并返回结果 JSON；校验失败 / 请求失败抛异常。"""
    method = (method or "GET").upper()
    if method not in _ALLOWED_METHODS:
        raise ValueError(
            f"不支持的方法 {method}，允许：{', '.join(sorted(_ALLOWED_METHODS))}"
        )
    if urllib.parse.urlsplit(url).scheme.lower() not in ("http", "https"):
        raise ValueError(f"仅支持 http/https 协议：{url}")
    if not _in_conversation(url, context):
        raise RuntimeError(
            f"URL {url} 未在对话中出现过：只能请求用户提供 / web_search 返回 / "
            "之前 http_request 结果的 URL"
        )

    # 续读（start_index > 0）优先复用缓存全文；从头读 / 无缓存则真实请求
    key = _cache_key(method, url, body)
    full = _page_cache.get(key) if start_index > 0 else None
    status = 0
    if full is None:
        resp = call(
            "http.request",
            method,
            url,
            headers=headers,
            body=body,
            timeout=_http_config.http_request_timeout_seconds,
        )
        if resp is None:
            raise RuntimeError("http.request 服务未注册（core.http 未导入）")
        status = resp.status
        if status >= 400:
            raise RuntimeError(f"HTTP {status}: {url}")
        is_html = method == "GET" and "html" in resp.content_type.lower()
        if raw or not is_html:
            full = resp.text
        else:
            full = extract_page(resp.text, url) or resp.text  # 提取失败退回原文
        full = full.strip()
        _page_cache.clear()  # 覆盖式缓存，只保留最近一次
        _page_cache[key] = full

    total = len(full)
    end = min(start_index + max_length, total)
    piece = full[start_index:end]
    return json.dumps(
        {
            "type": HttpRequestResultType.RESULT,
            "url": url,
            "method": method,
            "status": status or 0,
            "start_index": start_index,
            "end_index": end,
            "total_length": total,
            "has_more": end < total,
            "content": piece,
        },
        ensure_ascii=False,
    )


def _do_http_request_result(**kwargs) -> str:
    """执行一次 http_request，返回完整结果（外层 JSON）。失败宽容降级。"""
    try:
        return _do_request(**kwargs)
    except Exception as e:  # noqa: BLE001 —— 请求失败宽容降级为错误文本
        return json.dumps(
            {
                "type": HttpRequestResultType.ERROR,
                "url": kwargs.get("url", ""),
                "method": (kwargs.get("method") or "GET").upper(),
                "error": str(e),
            },
            ensure_ascii=False,
        )


def register(registry: ToolRegistry) -> None:
    """向 registry 注册 http_request 工具（需对话 context，走 needs_context）。"""

    def _fn(
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | None = None,
        max_length: int | None = None,
        start_index: int = 0,
        raw: bool = False,
        _context: str | None = None,
    ) -> str:
        # body 兼容字符串与对象（对象自动 JSON 化）
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False)
        elif body is not None and not isinstance(body, str):
            body = str(body)
        return _do_http_request_result(
            url=url,
            method=method,
            headers=headers,
            body=body,
            max_length=max_length or _http_config.http_request_max_chars,
            start_index=start_index,
            raw=raw,
            context=_context,
        )

    registry.register(
        "http_request",
        description=(
            "发起 HTTP 请求。只能请求对话中已出现的 URL（用户提供 / web_search "
            "返回 / 之前 http_request 的结果），不能访问需要认证的内容。"
            "GET 抓网页默认返回简化的正文 markdown（max_length 限长，内容未完可用 "
            "start_index 续读，取上次返回的 end_index）；POST/PUT/PATCH/DELETE "
            "可带 headers 与 body（对象自动转 JSON）。raw=true 时返回原始文本"
            "（如 HTML 源码 / JSON 原文）而非简化 markdown。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要请求的 URL（须已在对话中出现过）",
                },
                "method": {
                    "type": "string",
                    "description": "HTTP 方法，默认 GET",
                    "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                },
                "headers": {
                    "type": "object",
                    "description": "请求头（可选）",
                },
                "body": {
                    "type": "string",
                    "description": "请求体（POST/PUT/PATCH 用）：JSON 字符串或对象",
                },
                "max_length": {
                    "type": "integer",
                    "description": "返回内容最大长度（字符），默认 4000",
                },
                "start_index": {
                    "type": "integer",
                    "description": "续读起点（用上次返回的 end_index），默认 0",
                },
                "raw": {
                    "type": "boolean",
                    "description": "true 返回原始文本而非简化 markdown，默认 false",
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        },
        fn=_fn,
        needs_context=True,
    )