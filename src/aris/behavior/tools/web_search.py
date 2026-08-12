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

from ..registry import ToolRegistry

# Tavily API
_TAVILY_URL = "https://api.tavily.com/search"
_TAVILY_RESULTS = 5
# Tavily 返回页面正文，首期只要摘要，截断到该长度省 token
_TAVILY_SNIPPET_MAX = 200


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
            "max_results": _TAVILY_RESULTS,
            "include_answer": False,
        },
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()
    lines: list[str] = []
    for idx, item in enumerate(data.get("results", []), start=1):
        title = item.get("title", "")
        url = item.get("url", "")
        snippet = item.get("content", "")
        if len(snippet) > _TAVILY_SNIPPET_MAX:
            snippet = snippet[:_TAVILY_SNIPPET_MAX] + "…"
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
                "type": "web_search_error",
                "query": query,
                "error": f"联网搜索失败：{e}",
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "type": "web_search_results",
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
