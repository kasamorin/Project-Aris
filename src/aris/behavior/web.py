"""联网搜索执行层：驱动浏览器搜 Bing/Google，返回结构化结果。

职责：
- 用 BrowserManager 的页面访问搜索引擎结果页
- 解析出标题 / URL / 摘要，带上自增 id
- 返回外层 JSON（标注是联网搜索返回）+ 内部 markdown 的字符串，
  供 LLM 直接消化（JSON 只在最外层标识结构，内部用 md 省 token）

失败策略（宽容降级链，由 web_search 工具注册处编排）：
- 引擎反爬/无结果 → 换引擎（Google 失败降 Bing，Bing 失败降 Tavily）
- 本模块只负责「单引擎尝试」，失败抛异常，编排逻辑在上层
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from playwright.sync_api import Page

from .browser import BrowserManager

# 搜索结果超时（含页面加载 + 解析）
_SEARCH_TIMEOUT_MS = 15000

# 结果条目选择器（Bing / Google 结果页的 DOM 结构不同，分开写）
_BING_ITEM_SELECTOR = "li.b_algo"
_GOOGLE_ITEM_SELECTOR = "div.g"


@dataclass
class SearchResult:
    """一条搜索结果：标题 + 链接 + 摘要 + 自增 id。"""

    id: int
    title: str
    url: str
    snippet: str


def _build_url(engine: str, query: str) -> str:
    """拼搜索引擎结果页 URL。"""
    q = query.strip()
    if engine == "bing":
        return f"https://www.bing.com/search?q={q}&count=10"
    if engine == "google":
        return f"https://www.google.com/search?q={q}&num=10"
    raise ValueError(f"未知搜索引擎: {engine}")


def _clean(text: str | None) -> str:
    """清洗一段文本：去空白、压缩连续空白。"""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _parse_bing(page: Page) -> list[SearchResult]:
    """解析 Bing 结果页，返回结果列表（id 从 1 开始）。"""
    items = page.locator(_BING_ITEM_SELECTOR).all()
    results: list[SearchResult] = []
    for idx, item in enumerate(items, start=1):
        title_el = item.locator("h2 a")
        title = _clean(title_el.first.inner_text()) if title_el.count() else ""
        url = ""
        if title_el.count():
            url = title_el.first.get_attribute("href") or ""
        snippet = _clean(item.locator(".b_caption p").first.inner_text())
        if not snippet:
            snippet = _clean(item.locator("p").first.inner_text())
        if title:
            results.append(SearchResult(id=idx, title=title, url=url, snippet=snippet))
    return results


def _parse_google(page: Page) -> list[SearchResult]:
    """解析 Google 结果页，返回结果列表（id 从 1 开始）。"""
    items = page.locator(_GOOGLE_ITEM_SELECTOR).all()
    results: list[SearchResult] = []
    for idx, item in enumerate(items, start=1):
        title_el = item.locator("h3")
        title = _clean(title_el.first.inner_text()) if title_el.count() else ""
        url = ""
        # Google 结果链接在 h3 的父级 <a> 上
        link = item.locator("a").first
        if link.count():
            url = link.get_attribute("href") or ""
        snippet = _clean(
            item.locator('div[data-sncf], span[style*="height"]').first.inner_text()
        )
        if not snippet:
            snippet = _clean(item.locator("div").last.inner_text())
        if title:
            results.append(SearchResult(id=idx, title=title, url=url, snippet=snippet))
    return results


def search_engine(browser: BrowserManager, engine: str, query: str) -> list[SearchResult]:
    """在指定引擎搜索，返回结构化结果。

    raise: playwright 加载/解析失败或引擎无结果（如验证码页）时抛异常，
    由上层决定是否换引擎。
    """
    page: Page = browser.page
    page.goto(_build_url(engine, query), timeout=_SEARCH_TIMEOUT_MS)
    page.wait_for_timeout(1200)  # 等 JS 渲染出结果
    if engine == "bing":
        results = _parse_bing(page)
    elif engine == "google":
        results = _parse_google(page)
    else:
        raise ValueError(f"未知搜索引擎: {engine}")
    if not results:
        raise RuntimeError(f"{engine} 无搜索结果（可能触发验证码或反爬）")
    return results


def to_markdown(results: list[SearchResult]) -> str:
    """把结果列表渲染为内部 markdown 文本（标题带链接 + 摘要）。"""
    lines: list[str] = []
    for r in results:
        lines.append(f"{r.id}. [{r.title}]({r.url})")
        if r.snippet:
            lines.append(f"   {r.snippet}")
    return "\n".join(lines)
