"""web_search / web_open 走 core.http 的迁移验证（mock 服务，不依赖外网）。

通过 provide() 替换 `http.request` 服务为 fake，断言：
- Bing：两次 GET（首页 → 搜索）走命名会话 session="bing"，UA 为 Firefox
- Tavily：POST 到 api.tavily.com，body 带 api_key，无会话
- web_open：GET 抓取正文，无会话；web_common.extract_page 提取

运行：uv run python test_web_migrate.py
"""

from __future__ import annotations

import base64
import json
import os
import sys

from loguru import logger

logger.remove()
logger.add(sys.stderr, level="WARNING")

import aris.core.llm.notify as notify

notify.broadcast = lambda *a, **k: None  # noqa: E731

from aris.core.bus import provide  # noqa: E402
from aris.core.http import HttpResponse  # noqa: E402
from aris.behavior.tools import web_search  # noqa: E402

_pass = 0
_fail = 0

_calls: list[dict] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {name}")
    else:
        _fail += 1
        print(f"  FAIL  {name}  {detail}")


_BING_URL = "https://www.bing.com/"
_SEARCH_URL = "https://www.bing.com/search?q=%E6%B5%8B%E8%AF%95&form=QBRE"
_TAVILY_URL = "https://api.tavily.com/search"


def _fake_http(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: str | None = None,
    timeout: float = 20.0,
    follow_redirects: bool = True,
    session: str | None = None,
) -> HttpResponse:
    """假 http.request 服务：记录调用并按 URL 返回构造好的响应。"""
    _calls.append(
        {
            "method": method,
            "url": url,
            "headers": headers,
            "body": body,
            "timeout": timeout,
            "session": session,
        }
    )
    if url == _BING_URL:
        return HttpResponse(200, "<html></html>", url, "text/html")
    if url == _SEARCH_URL:
        b64 = base64.urlsafe_b64encode("https://example.com/真页面".encode()).decode().rstrip("=")
        html = (
            '<ol><li class="b_algo"><h2><a href="/ck/a?u=a1' + b64 + '">Bing 标题</a></h2>'
            "<p>Bing 摘要内容片段。</p></li></ol>"
        )
        return HttpResponse(200, html, url, "text/html")
    if url == _TAVILY_URL:
        data = json.dumps(
            {"results": [{"title": "T1", "url": "https://example.com/1", "content": "Tavily 摘要内容"}]},
            ensure_ascii=False,
        )
        return HttpResponse(200, data, url, "application/json")
    return HttpResponse(
        200,
        "<html><body><article><h1>页面标题</h1><p>网页正文段落内容。</p></article></body></html>",
        url,
        "text/html",
    )


def test_bing_session() -> None:
    global _calls
    _calls = []
    web_search._recent_results.clear()
    old = web_search._search_config.prefer_engine
    web_search._search_config.prefer_engine = "bing"
    try:
        out = json.loads(web_search._do_web_search("测试"))
    finally:
        web_search._search_config.prefer_engine = old
    check("成功标识", out["type"] == "web_search_results", str(out.get("type")))
    check("引擎为 bing", out["engine"] == "bing", str(out.get("engine")))
    check("含标题", "Bing 标题" in out["results"])
    check("解码真实 URL", "https://example.com/真页面" in out["results"])
    check("先首页后搜索", [c["url"] for c in _calls] == [_BING_URL, _SEARCH_URL])
    check("两次均带命名会话", all(c["session"] == "bing" for c in _calls), str(_calls))
    check("首页用 Firefox UA", _calls[0]["headers"].get("User-Agent") == web_search._BING_UA)
    check("结果已入缓存", web_search._recent_results.get(1, {}).get("url") == "https://example.com/真页面")


def test_tavily_fallback() -> None:
    global _calls
    _calls = []
    web_search._recent_results.clear()
    os.environ["TAVILY_API_KEY"] = "test-key"
    old = web_search._search_config.prefer_engine
    web_search._search_config.prefer_engine = "tavily"
    try:
        out = json.loads(web_search._do_web_search("测试"))
    finally:
        web_search._search_config.prefer_engine = old
        os.environ.pop("TAVILY_API_KEY", None)
    check("降级成功标识", out["type"] == "web_search_results", str(out.get("type")))
    check("引擎为 tavily", out["engine"] == "tavily", str(out.get("engine")))
    check("含 Tavily 标题", "T1" in out["results"])
    post = _calls[-1]
    check("POST 到 Tavily", post["method"] == "POST" and post["url"] == _TAVILY_URL, str(post["url"]))
    check("无会话", post["session"] is None, str(post["session"]))
    payload = json.loads(post["body"] or "{}")
    check("body 带 api_key", payload.get("api_key") == "test-key", str(payload))
    check("带 JSON 头", post["headers"].get("Content-Type") == "application/json")


def test_web_open() -> None:
    global _calls
    _calls = []
    web_search._recent_results = {1: {"title": "T", "url": "http://example.com/x"}}
    out = json.loads(web_search._do_web_open_result(1))
    check("成功标识", out["type"] == "web_open_result", str(out.get("type")))
    check("正文已提取", "网页正文段落内容" in out["content"], repr(out.get("content")))
    got = _calls[-1]
    check("GET 抓取目标 URL", got["method"] == "GET" and got["url"] == "http://example.com/x", str(got["url"]))
    check("无会话", got["session"] is None, str(got["session"]))


def main() -> None:
    provide("http.request", _fake_http)
    tests = [test_bing_session, test_tavily_fallback, test_web_open]
    for t in tests:
        print(f"\n== {t.__name__}")
        try:
            t()
        except Exception as e:  # noqa: BLE001
            global _fail
            _fail += 1
            print(f"  EXC   {type(e).__name__}: {e}")
    print(f"\n----\nPASS {_pass} / FAIL {_fail}")


if __name__ == "__main__":
    main()