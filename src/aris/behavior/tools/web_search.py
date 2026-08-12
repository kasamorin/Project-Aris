"""内置工具：web_search / web_open —— 联网搜索与网页正文读取。

搜索走 Tavily API（专为 LLM 设计、无反爬，TAVILY_API_KEY 走 .env）。
web_search 返回格式（设计哲学：外层 JSON 标识是联网搜索结果，内部用
markdown 省 token）：
    {"type": "web_search_results", "query": "...", "engine": "tavily",
     "results": "1. [标题](url)\\n   摘要\\n2. ..."}
每条结果自带自增 id（第 1 条为 1），web_search 同时把 id→url 映射存入
模块级 `_recent_results`，供 web_open 按 id 点开读正文：
    {"type": "web_open_result", "id": 2, "url": "...",
     "content": "标题 + 原文链接 + 正文（截断省 token）"}

失败策略（宽容降级）：搜索/抓取失败返回错误文本 JSON 给模型消化，
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


class WebOpenResultType(StrEnum):
    """web_open 工具返回结果的外层标识。"""

    RESULT = "web_open_result"      # 正文读取成功
    ERROR = "web_open_error"        # 读取失败（宽容降级）


@dataclass
class SearchConfig:
    """联网搜索可调参数（config/search.toml）。"""

    timeout_seconds: float = 15.0
    results_count: int = 5
    snippet_max_len: int = 200
    webopen_timeout_seconds: float = 20.0
    webopen_max_chars: int = 4000


_search_config = load_config(SearchConfig(), "search.toml")

# Tavily API 端点（固定实现细节，不可调）
_TAVILY_URL = "https://api.tavily.com/search"

# 最近一次搜索的 id → {title, url}，供 web_open 按 id 点开（覆盖式缓存）
_recent_results: dict[int, dict[str, str]] = {}

# 抓取网页用的浏览器 UA（部分站点对无 UA 请求 403）
_WEB_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def _tavily_search(query: str) -> str:
    """Tavily 搜索，返回 markdown 结果文本；失败抛异常。

    同时把 id→{title, url} 写入模块级 `_recent_results`（覆盖式），
    供 web_open 按 id 点开读正文。
    """
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
    items = data.get("results", [])
    lines: list[str] = []
    _recent_results.clear()
    for idx, item in enumerate(items, start=1):
        title = item.get("title", "")
        url = item.get("url", "")
        snippet = item.get("content", "")
        if len(snippet) > _search_config.snippet_max_len:
            snippet = snippet[:_search_config.snippet_max_len] + "…"
        lines.append(f"{idx}. [{title}]({url})")
        if snippet:
            lines.append(f"   {snippet}")
        _recent_results[idx] = {"title": title, "url": url}
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


def _do_web_open(result_id: int) -> str:
    """按搜索结果 id 抓取并提取正文，返回 markdown；失败抛异常。"""
    entry = _recent_results.get(result_id)
    if entry is None:
        raise RuntimeError(
            f"id {result_id} 不在最近的搜索结果里（需要先 web_search，且 id 有效）"
        )
    url = entry["url"]
    import httpx

    resp = httpx.get(
        url,
        headers={"User-Agent": _WEB_UA},
        timeout=_search_config.webopen_timeout_seconds,
        follow_redirects=True,
    )
    resp.raise_for_status()

    # trafilatura：过滤导航/页脚/广告，提取正文纯文本
    from trafilatura import extract

    body = extract(resp.text, url=url)
    if not body:
        raise RuntimeError(f"网页正文提取为空（可能是动态渲染页面）：{url}")
    body = body.strip()
    if len(body) > _search_config.webopen_max_chars:
        body = body[:_search_config.webopen_max_chars] + "…"

    title = entry.get("title") or url
    return f"# {title}\n\n原文链接：{url}\n\n{body}"


def _do_web_open_result(result_id: int) -> str:
    """执行一次 web_open，返回完整结果（外层 JSON + 内部 markdown）。"""
    try:
        markdown = _do_web_open(result_id)
    except Exception as e:  # noqa: BLE001 —— 读取失败宽容降级为错误文本
        return json.dumps(
            {
                "type": WebOpenResultType.ERROR,
                "id": result_id,
                "error": f"网页读取失败：{e}",
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "type": WebOpenResultType.RESULT,
            "id": result_id,
            "content": markdown,
        },
        ensure_ascii=False,
    )


def register(registry: ToolRegistry) -> None:
    """向 registry 注册 web_search 与 web_open 工具。"""

    def _fn(query: str) -> str:
        return _do_web_search(query)

    registry.register(
        "web_search",
        description=(
            "联网搜索。当用户询问实时信息、需要查资料时使用。"
            "参数 query 为搜索关键词。返回搜索结果列表，每条带 id，"
            "可用 web_open 按 id 点开读正文。"
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

    def _open_fn(id: int) -> str:
        return _do_web_open_result(id)

    registry.register(
        "web_open",
        description=(
            "读取某条搜索结果（web_search 返回的 id）的网页正文。"
            "当搜索结果摘要不够、需要看完整内容时使用。"
            "参数 id 必须是最近一次 web_search 返回结果里的 id。"
            "返回标题 + 原文链接 + 正文（截断）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "id": {
                    "type": "integer",
                    "description": "搜索结果条目的 id（web_search 返回，从 1 开始）",
                },
            },
            "required": ["id"],
            "additionalProperties": False,
        },
        fn=_open_fn,
    )
