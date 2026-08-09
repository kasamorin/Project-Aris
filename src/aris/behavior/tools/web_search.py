"""内置工具：web_search —— 联网搜索（Playwright Firefox 主链路 + Tavily 兜底）。

搜索行为像人：默认先试 Google，反爬/失败降级 Bing，再失败降级 Tavily。
多次失败会把 Bing 提为优先引擎（Bing 反爬相对温和，命中率高）。

返回格式（设计哲学：外层 JSON 标识是联网搜索结果，内部用 markdown 省 token）：
    {"type": "web_search_results", "query": "...", "engine": "bing",
     "results": "1. [标题](url)\\n   摘要\\n2. ..."}
每条结果自带自增 id（第 1 条为 1），供后续 web_open 按 id 点开。

宽容降级：浏览器启动失败 / 全部引擎失败时返回错误文本给模型消化，
不抛到 UI（registry.execute 也会兜底）。
"""

from __future__ import annotations

import json
import os

from ..browser import BrowserManager
from ..registry import ToolRegistry
from .. import web as web_engine

# Bing 被提为优先前，Google 连续失败多少次触发
_GOOGLE_FAILS_TO_PREFER_BING = 3

# 模块级失败计数：多次失败后把 Bing 提为优先（跨调用保持）
_google_fail_streak = 0
_prefer_bing = False

# Tavily API（降级兜底）
_TAVILY_URL = "https://api.tavily.com/search"
_TAVILY_RESULTS = 5
# Tavily 返回页面正文，首期只要摘要，截断到该长度省 token
_TAVILY_SNIPPET_MAX = 200


def _tavily_search(query: str) -> str:
    """Tavily 兜底搜索，返回与主链路一致的 markdown 文本；失败抛异常。"""
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


def _pick_engine(preferred: str) -> str:
    """决定本轮尝试的引擎顺序。"""
    if preferred in {"bing", "google"}:
        return preferred
    if _prefer_bing:
        return "bing"
    return "google"


def _search(browser: BrowserManager, query: str, engine: str) -> str:
    """主链路搜索（浏览器驱动引擎），返回 markdown 文本。"""
    results = web_engine.search_engine(browser, engine, query)
    return web_engine.to_markdown(results)


def _do_web_search(browser: BrowserManager, query: str, engine: str = "google") -> str:
    """执行一次联网搜索，返回完整结果（外层 JSON + 内部 markdown）。"""
    global _google_fail_streak, _prefer_bing

    first = _pick_engine(engine)
    engines = [first] + [e for e in ("google", "bing") if e != first]
    last_error = ""
    used_engine = ""
    markdown = ""

    for eng in engines:
        try:
            markdown = _search(browser, query, eng)
            used_engine = eng
            if eng == "google":
                _google_fail_streak = 0
            elif eng == "bing":
                _prefer_bing = True
            break
        except Exception as e:  # noqa: BLE001 —— 引擎失败尝试下一家
            last_error = str(e)
            if eng == "google":
                _google_fail_streak += 1
                if _google_fail_streak >= _GOOGLE_FAILS_TO_PREFER_BING:
                    _prefer_bing = True

    if not markdown:
        # 双引擎都失败 → Tavily 兜底
        try:
            markdown = _tavily_search(query)
            used_engine = "tavily"
        except Exception as e:  # noqa: BLE001 —— 兜底也失败，宽容降级
            return json.dumps(
                {
                    "type": "web_search_error",
                    "query": query,
                    "error": f"联网搜索全部失败（{last_error}；Tavily: {e}）",
                },
                ensure_ascii=False,
            )

    return json.dumps(
        {
            "type": "web_search_results",
            "query": query,
            "engine": used_engine,
            "results": markdown,
        },
        ensure_ascii=False,
    )


def register(registry: ToolRegistry, browser: BrowserManager | None = None) -> None:
    """向 registry 注册 web_search 工具。

    browser 由调用方（ChatSession）注入，实现浏览器会话内常驻；
    未注入时工具内部惰性自建（默认 profile 目录）。
    """
    if browser is None:
        browser = BrowserManager()

    def _fn(query: str, engine: str = "google") -> str:
        return _do_web_search(browser, query, engine)

    registry.register(
        "web_search",
        description=(
            "联网搜索。当用户询问实时信息、需要查资料时使用。"
            "参数 query 为搜索关键词，engine 可选 bing/google（默认 google，"
            "失败自动降级）。返回搜索结果列表，每条带 id，可让用户选择后继续深入。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，尽量简洁准确",
                },
                "engine": {
                    "type": "string",
                    "enum": ["bing", "google"],
                    "description": "搜索引擎（可选，默认 google）",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        fn=_fn,
    )
