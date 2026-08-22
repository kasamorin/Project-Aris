"""http_request 工具集成测试（本地 mock HTTP server，不依赖外网）。

覆盖：
- GET 长文：有界输出 + has_more + start_index 续读（缓存复用）
- raw=true 返回原始文本
- POST：请求体回显（JSON 原文返回）
- 404 → 宽容降级错误
- URL 规则：host 未出现在对话 → 拒绝；出现 → 放行
- 方法白名单 / 协议白名单 / 命名会话 cookie 连续

原根目录手写脚本迁移为 pytest（2026-08-18）。
"""

from __future__ import annotations

import json

from aris.behavior.registry import ToolRegistry

from support.mock_http import MockHTTP


def call_tool(reg: ToolRegistry, arguments: dict, context: str | None = None) -> dict:
    raw = reg.execute("http_request", arguments, context=context)
    return json.loads(raw)


def test_get_bounded(http_server: MockHTTP, http_registry: ToolRegistry) -> None:
    url = f"{http_server.base_url}/page"
    out = call_tool(http_registry, {"url": url}, context=url)
    assert out["type"] == "http_request_result", str(out.get("type"))
    assert out["status"] == 200, str(out.get("status"))
    assert bool(out["content"]), repr(out["content"][:30])
    assert out["end_index"] - out["start_index"] == len(out["content"])
    assert out["has_more"] is True, str(out.get("has_more"))
    assert out["total_length"] > len(out["content"])


def test_continuation(http_server: MockHTTP, http_registry: ToolRegistry) -> None:
    url = f"{http_server.base_url}/page"
    ctx = url
    first = call_tool(http_registry, {"url": url, "max_length": 2000}, context=ctx)
    e1 = first["end_index"]
    total = first["total_length"]
    assert bool(first["content"])
    second = call_tool(http_registry, {"url": url, "max_length": 2000, "start_index": e1}, context=ctx)
    assert second["end_index"] > e1, f"{second['end_index']} vs {e1}"
    assert second["content"] != first["content"]
    assert second["total_length"] == total
    assert second["end_index"] <= total
    # 从头重读（start_index=0）应重新请求，切片从 0 开始
    again = call_tool(http_registry, {"url": url, "max_length": 2000}, context=ctx)
    assert again["start_index"] == 0 and again["content"] == first["content"]


def test_raw(http_server: MockHTTP, http_registry: ToolRegistry) -> None:
    url = f"{http_server.base_url}/raw"
    out = call_tool(http_registry, {"url": url, "raw": True}, context=url)
    assert out["content"].startswith("<html>"), repr(out["content"][:20])


def test_post(http_server: MockHTTP, http_registry: ToolRegistry) -> None:
    url = f"{http_server.base_url}/api"
    out = call_tool(http_registry, {"url": url, "method": "POST", "body": {"a": 1}}, context=url)
    assert out["type"] == "http_request_result", str(out.get("type"))
    assert out["status"] == 200, str(out.get("status"))
    parsed = json.loads(out["content"])
    assert parsed.get("method") == "POST", repr(parsed)
    assert parsed.get("body") == '{"a": 1}', repr(parsed.get("body"))


def test_404(http_server: MockHTTP, http_registry: ToolRegistry) -> None:
    url = f"{http_server.base_url}/nope"
    out = call_tool(http_registry, {"url": url}, context=url)
    assert out["type"] == "http_request_error", str(out.get("type"))
    assert "404" in out["error"], repr(out.get("error"))


def test_url_rule(http_server: MockHTTP, http_registry: ToolRegistry) -> None:
    url = f"{http_server.base_url}/page"
    # host 未出现在对话 → 拒绝
    out = call_tool(http_registry, {"url": url}, context="一段与 URL 无关的对话内容")
    assert out["type"] == "http_request_error", str(out.get("type"))
    assert "未在对话中出现" in out["error"], repr(out.get("error"))
    # host 出现在对话 → 放行（软校验：提过一次即可）
    out2 = call_tool(http_registry, {"url": url}, context="用户提到想看看 127.0.0.1 的内容")
    assert out2["type"] == "http_request_result", str(out2.get("type"))


def test_method_whitelist(http_server: MockHTTP, http_registry: ToolRegistry) -> None:
    url = f"{http_server.base_url}/page"
    out = call_tool(http_registry, {"url": url, "method": "TRACE"}, context=url)
    assert out["type"] == "http_request_error", str(out.get("type"))
    assert "不支持的方法" in out["error"], repr(out.get("error"))


def test_scheme_whitelist(http_server: MockHTTP, http_registry: ToolRegistry) -> None:
    out = call_tool(http_registry, {"url": "ftp://example.com/x"}, context="ftp://example.com/x")
    assert out["type"] == "http_request_error", str(out.get("type"))
    assert "仅支持 http/https" in out["error"], repr(out.get("error"))


def test_session(http_server: MockHTTP) -> None:
    url = f"{http_server.base_url}/cookie"
    from aris.core import call

    # 无 session：每次新连接，cookie 不共享
    r1 = call("http.request", "GET", url)
    r2 = call("http.request", "GET", url)
    assert "sid=abc123" not in r1.text and "sid=abc123" not in r2.text
    # 命名会话：cookie 连续（第一次 Set-Cookie，第二次带回）
    s1 = call("http.request", "GET", url, session="tsess")
    s2 = call("http.request", "GET", url, session="tsess")
    assert "sid=abc123" in s2.text, repr(s2.text)
    assert "cookie=" in s1.text, repr(s1.text)
