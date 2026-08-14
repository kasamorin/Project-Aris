"""内置工具：web_search / web_open —— 联网搜索与网页正文读取。

搜索走多引擎链路（2026-08-14 定案）：**Bing 直连为主，Tavily 兜底**。
- Bing：HTTP 直连搜索页（无 API key、免费、中文结果好），用浏览器 UA +
  URL 编码请求；结果链接是 /ck/a 重定向包装，解码 u= 参数拿真实 URL。
- Tavily：TAVILY_API_KEY 走 .env，Bing 失败（429/超时/无结果）时自动降级。
- 引擎顺序由 SearchConfig.prefer_engine 决定（默认 "bing"）。

web_search 返回格式（设计哲学：外层 JSON 标识是联网搜索结果，内部用
markdown 省 token）：
    {"type": "web_search_results", "query": "...", "engine": "bing|tavily",
     "results": "1. [标题](url)\\n   摘要\\n2. ..."}
每条结果自带自增 id（第 1 条为 1），web_search 同时把 id→url 映射存入
模块级 `_recent_results`，供 web_open 按 id 点开读正文：
    {"type": "web_open_result", "id": 2, "url": "...",
     "content": "标题 + 原文链接 + 正文（截断省 token）"}

失败策略（宽容降级）：所有引擎搜索失败返回错误文本 JSON 给模型消化，
不抛到 UI（registry.execute 也会兜底）。
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from loguru import logger

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

    prefer_engine: str = "bing"  # 首选引擎；"bing"/"tavily"/"auto"(按语言分流)
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

# Bing 搜索用 Firefox UA（无需 sec-ch-ua 配套指纹，实测结果更稳定）
_BING_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"


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
        snippet = _clean_snippet(item.get("content", ""))
        lines.append(f"{idx}. [{title}]({url})")
        if snippet:
            lines.append(f"   {snippet}")
        _recent_results[idx] = {"title": title, "url": url}
    if not lines:
        raise RuntimeError("Tavily 无搜索结果")
    return "\n".join(lines)


def _clean_snippet(raw: str) -> str:
    """清洗摘要：HTML 实体解码 + 折叠空白 + 取最长的连续文本块。

    Tavily 的 content 是页面正文原始片段，常混入导航/元数据噪音
    （实测见「博客园logo / 搜索 / 订阅数」等）。取最长的文本块可
    大概率命中正文主干，省 token 且不给模型添乱。
    """
    text = html.unescape(raw)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    blocks = [b.strip() for b in text.splitlines() if b.strip()]
    longest = max(blocks, key=len) if blocks else text.strip()
    if len(longest) > _search_config.snippet_max_len:
        longest = longest[: _search_config.snippet_max_len] + "…"
    return longest


def _decode_bing_redirect(href: str) -> str:
    """解码 Bing /ck/a 重定向链接的 u= 参数（base64 包装 URL）。

    实测格式：`https://www.bing.com/ck/a?...&u=a1<base64(真实URL)>`。
    解码失败返回空串（上层保留原链接，web_open 跟随重定向兜底）。
    """
    if not href.startswith(("https://www.bing.com/ck/a", "/ck/a")):
        return ""
    params = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
    raw = (params.get("u") or [""])[0]
    if not raw:
        return ""
    b64 = raw[2:] if raw.startswith("a1") else raw
    try:
        return base64.urlsafe_b64decode(b64 + "===").decode()
    except Exception:  # noqa: BLE001 —— 解码失败不值得抛错，留原链接即可
        return ""


def _bing_search(query: str) -> str:
    """Bing 网页搜索，返回 markdown 结果文本；失败抛异常。

    关键实现细节（2026-08-14 实测，直接影响结果质量）：
    - 用 httpx.Client 会话：先访问首页拿 cookie（MUID 等），再搜索。
      不带 cookie 时 Bing 偶发返回官网首页等低质量结果，稳定性差。
    - 带 form=QBRE 参数（真实浏览器搜索请求带此参数）。
    - UA 用 Firefox（无需 sec-ch-ua 配套指纹，实测结果稳定）；
      Chrome UA 需配 sec-ch-ua 系列头，否则指纹不完整。
    - 链接是 /ck/a 重定向包装，解码 u= 参数（base64）拿真实 URL。
    """
    from bs4 import BeautifulSoup
    import httpx

    headers = {
        "User-Agent": _BING_UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    encoded = urllib.parse.quote(query)
    search_url = f"https://www.bing.com/search?q={encoded}&form=QBRE"
    with httpx.Client(
        headers=headers,
        timeout=_search_config.timeout_seconds,
        follow_redirects=True,
    ) as client:
        client.get("https://www.bing.com/")
        resp = client.get(search_url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    items = soup.select("li.b_algo")
    if not items:
        raise RuntimeError("Bing 无搜索结果")

    lines: list[str] = []
    _recent_results.clear()
    for idx, li in enumerate(items[: _search_config.results_count], start=1):
        a = li.select_one("h2 a")
        if a is None:
            continue
        title = a.get_text(" ", strip=True)
        href = a.get("href", "")
        url = _decode_bing_redirect(href) or href
        p = li.select_one("p")
        snippet = _clean_snippet(p.get_text(" ", strip=True)) if p else ""
        lines.append(f"{idx}. [{title}]({url})")
        if snippet:
            lines.append(f"   {snippet}")
        _recent_results[idx] = {"title": title, "url": url}
    if not lines:
        raise RuntimeError("Bing 无有效搜索结果")
    return "\n".join(lines)


# 可用搜索引擎：name → 实现。prefer_engine 决定尝试顺序，其余依次兜底。
_ENGINES: dict[str, Callable[[str], str]] = {
    "bing": _bing_search,
    "tavily": _tavily_search,
}


def _has_cjk(text: str) -> bool:
    """是否含中日韩统一表意文字（用于 auto 引擎分流）。

    auto 模式：含中文走 Tavily、否则走 Bing。该分流是 2026-08-14 排查中的
    备选方案（当时 Bing 请求缺 cookie/form=QBRE 参数，中文结果质量差）；
    补齐关键参数后 Bing 中文已精准，默认 prefer_engine 改回 "bing"，
    auto 仅保留作可选开关。
    """
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _ordered_engines(query: str) -> list[tuple[str, Callable[[str], str]]]:
    """决定引擎尝试顺序（prefer 先行，其余依次兜底）。

    prefer_engine：
    - "bing"/"tavily"：固定该引擎优先，另一个兜底
    - "auto"：按查询语言分流（2026-08-14 定案前的备选方案，默认已改回 bing）
    """
    preferred = _search_config.prefer_engine
    if preferred == "auto":
        preferred = "tavily" if _has_cjk(query) else "bing"
    elif preferred not in ("bing", "tavily"):
        logger.warning(f"未知 prefer_engine={preferred!r}，回退 bing")
        preferred = "bing"
    order = [preferred] + [k for k in _ENGINES if k != preferred]
    return [(k, _ENGINES[k]) for k in order]


def _do_web_search(query: str) -> str:
    """执行一次联网搜索，按 prefer_engine 顺序尝试各引擎。

    第一个成功的引擎作为结果来源（engine 字段如实标识）；
    全部失败才返回错误 JSON（宽容降级）。
    """
    for name, fn in _ordered_engines(query):
        try:
            markdown = fn(query)
        except Exception as e:  # noqa: BLE001 —— 单引擎失败继续尝试下一个
            logger.warning(f"搜索引擎 {name} 失败，尝试下一个: {e}")
            continue
        return json.dumps(
            {
                "type": WebSearchResultType.RESULTS,
                "query": query,
                "engine": name,
                "results": markdown,
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "type": WebSearchResultType.ERROR,
            "query": query,
            "error": "所有搜索引擎均失败（bing/tavily）",
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
