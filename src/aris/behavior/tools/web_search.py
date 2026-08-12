"""内置工具：web_search —— 联网搜索（Tavily API 主链路）。

搜索走 Tavily API（专为 LLM 设计、无反爬，TAVILY_API_KEY 走 .env）。
返回格式（设计哲学：外层 JSON 标识是联网搜索结果，内部用 markdown 省 token）：
    {"type": "web_search_results", "query": "...", "engine": "tavily",
     "results": "1. [标题](url)\\n   摘要\\n2. ..."}
每条结果自带自增 id（第 1 条为 1），供后续 web_open 按 id 点开。

失败策略（宽容降级）：Tavily 失败返回错误文本 JSON 给模型消化，
不抛到 UI（registry.execute 也会兜底）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import StrEnum

from aris.cfgtoml import load_config
from ..registry import ToolRegistry


class WebSearchResultType(StrEnum):
    """联网搜索工具返回结果的外层标识。"""

    RESULTS = "web_search_results"  # 搜索成功
    ERROR = "web_search_error"      # 搜索失败（宽容降级）


@dataclass
class SearchConfig:
    """联网搜索可调参数（config/search.toml）。"""

    timeout_seconds: float = 15.0
    results_count: int = 5
    snippet_max_len: int = 200


_search_config = load_config(SearchConfig(), "search.toml")

# Tavily API 端点（固定实现细节，不可调）
_TAVILY_URL = "https://api.tavily.com/search"


def _tavily_search(query: str) -> str:
    """Tavily 搜索，返回 markdown 结果文本；失败抛异常。"""
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        raise RuntimeError("TAVILY_API_KEY 未配置")
    import httpx

    resp = httpx.post(
        _TAVILY_URL,
        json={
            "api_key": key,
            "query": query,
            "max_results": _search_config.results_count,
            "include_answer": False,
        },
        timeout=_search_config.timeout_seconds,
    )
    resp.raise_for_status()
    data = resp.json()
    lines: list[str] = []
    for idx, item in enumerate(data.get("results", []), start=1):
        title = item.get("title", "")
        url = item.get("url", "")
        snippet = item.get("content", "")
        if len(snippet) > _search_config.snippet_max_len:
            snippet = snippet[:_search_config.snippet_max_len] + "…"
        lines.append(f"{idx}. [{title}]({url})")
        if snippet:
            lines.append(f"   {snippet}")
    if not lines:
        raise RuntimeError("Tavily 无搜索结果")
    return "\n".join(lines)


def _do_web_search(query: str) -> str:
    """执行一次联网搜索，返回完整结果（外层 JSON + 内部 markdown）。"""
    try:
        markdown = _tavily_search(query)
    except Exception as e:  # noqa: BLE001 —— 搜索失败宽容降级为错误文本
        return json.dumps(
            {
                "type": WebSearchResultType.ERROR,
                "query": query,
                "error": f"联网搜索失败：{e}",
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "type": WebSearchResultType.RESULTS,
            "query": query,
            "engine": "tavily",
            "results": markdown,
        },
        ensure_ascii=False,
    )


def register(registry: ToolRegistry) -> None:
    """向 registry 注册 web_search 工具。"""

    def _fn(query: str) -> str:
        return _do_web_search(query)

    registry.register(
        "web_search",
        description=(
            "联网搜索。当用户询问实时信息、需要查资料时使用。"
            "参数 query 为搜索关键词。返回搜索结果列表，每条带 id，"
            "可让用户选择后继续深入。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，尽量简洁准确",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        fn=_fn,
    )
