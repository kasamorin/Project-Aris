"""web_search / web_open 走 core.http 的迁移验证（mock 服务，不依赖外网）。

通过 provide() 临时替换 `http.request` 服务为 fake，断言：
- Bing：两次 GET（首页 → 搜索）走命名会话 session="bing"，UA 为 Firefox
- Tavily：POST 到 api.tavily.com，body 带 api_key，无会话
- web_open：GET 抓取正文，无会话；web_common.extract_page 提取

fake 服务在测试后恢复原 http.request，避免污染同进程其他测试（如
test_http_request 里走真实 call("http.request") 的用例）。

原根目录手写脚本迁移为 pytest（2026-08-18）。
"""

from __future__ import annotations

import base64
import json
import os

import pytest

from aris.core import bus
from aris.core.bus import provide
from aris.core.http import HttpResponse
from aris.behavior.tools import web_search

_calls: list[dict] = []

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


@pytest.fixture
def fake_http():
    """临时替换 http.request 服务为 _fake_http，测试后恢复原服务。"""
    original = bus._services.get("http.request")
    provide("http.request", _fake_http)
    yield
    if original is not None:
        bus._services["http.request"] = original
    else:
        bus._services.pop("http.request", None)


def test_bing_session(fake_http) -> None:
    global _calls
    _calls = []
    web_search._recent_results.clear()
    old = web_search._search_config.prefer_engine
    web_search._search_config.prefer_engine = "bing"
    try:
        out = json.loads(web_search._do_web_search("测试"))
    finally:
        web_search._search_config.prefer_engine = old
    assert out["type"] == "web_search_results", str(out.get("type"))
    assert out["engine"] == "bing", str(out.get("engine"))
    assert "Bing 标题" in out["results"]
    assert "https://example.com/真页面" in out["results"]
    assert [c["url"] for c in _calls] == [_BING_URL, _SEARCH_URL]
    assert all(c["session"] == "bing" for c in _calls), str(_calls)
    assert _calls[0]["headers"].get("User-Agent") == web_search._BING_UA
    assert web_search._recent_results.get(1, {}).get("url") == "https://example.com/真页面"


def test_tavily_fallback(fake_http, monkeypatch) -> None:
    global _calls
    _calls = []
    web_search._recent_results.clear()
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    old = web_search._search_config.prefer_engine
    web_search._search_config.prefer_engine = "tavily"
    try:
        out = json.loads(web_search._do_web_search("测试"))
    finally:
        web_search._search_config.prefer_engine = old
    assert out["type"] == "web_search_results", str(out.get("type"))
    assert out["engine"] == "tavily", str(out.get("engine"))
    assert "T1" in out["results"]
    post = _calls[-1]
    assert post["method"] == "POST" and post["url"] == _TAVILY_URL, str(post["url"])
    assert post["session"] is None, str(post["session"])
    payload = json.loads(post["body"] or "{}")
    assert payload.get("api_key") == "test-key", str(payload)
    assert post["headers"].get("Content-Type") == "application/json"


def test_web_open(fake_http) -> None:
    global _calls
    _calls = []
    web_search._recent_results = {1: {"title": "T", "url": "http://example.com/x"}}
    out = json.loads(web_search._do_web_open_result(1))
    assert out["type"] == "web_open_result", str(out.get("type"))
    assert "网页正文段落内容" in out["content"], repr(out.get("content"))
    got = _calls[-1]
    assert got["method"] == "GET" and got["url"] == "http://example.com/x", str(got["url"])
    assert got["session"] is None, str(got["session"])
