"""http_request 工具集成测试（本地 mock HTTP server，不依赖外网）。

覆盖：
- GET 长文：有界输出 + has_more + start_index 续读（缓存复用）
- raw=true 返回原始文本
- POST：请求体回显（JSON 原文返回）
- 404 → 宽容降级错误
- URL 规则：host 未出现在对话 → 拒绝；出现 → 放行
- 方法白名单 / 协议白名单

运行：uv run python test_http_request.py
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from loguru import logger

logger.remove()
logger.add(sys.stderr, level="WARNING")

import aris.core.llm.notify as notify

notify.broadcast = lambda *a, **k: None  # noqa: E731

from aris.behavior.registry import ToolRegistry  # noqa: E402
from aris.behavior.tools.http_request import register as reg_http  # noqa: E402

_pass = 0
_fail = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {name}")
    else:
        _fail += 1
        print(f"  FAIL  {name}  {detail}")


LONG_HTML = (
    "<html><body><article><h1>长文标题</h1>"
    + "".join(
        f"<p>这是第 {i} 段正文内容，用于测试 http_request 的长文分页续读、"
        "有界输出与缓存复用。重复一些文字以撑大体积。</p>"
        for i in range(120)
    )
    + "</article></body></html>"
)

RAW_HTML = "<html><body><div id='x'>raw 原始内容</div></body></html>"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D102
        pass

    def _send(self, code: int, body: str, ctype: str = "text/html; charset=utf-8") -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/page"):
            self._send(200, LONG_HTML)
        elif self.path.startswith("/raw"):
            self._send(200, RAW_HTML)
        elif self.path.startswith("/api"):
            self._send(200, '{"method": "GET"}', "application/json")
        elif self.path.startswith("/cookie"):
            cookie = self.headers.get("Cookie", "")
            if not cookie:
                self.send_response(200)
                self.send_header("Set-Cookie", "sid=abc123; Path=/")
            else:
                self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            body = f"cookie={cookie}".encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._send(404, "not found")

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode()
        body = json.dumps({"method": "POST", "body": raw}, ensure_ascii=False)
        self._send(200, body, "application/json")


class MockHTTP:
    """本地 mock HTTP 服务：启动/停止 + base_url。"""

    def __init__(self) -> None:
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._httpd.server_address[1]}"

    def start(self) -> "MockHTTP":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


def make_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg_http(reg)
    return reg


def call_tool(reg: ToolRegistry, arguments: dict, context: str | None = None) -> dict:
    raw = reg.execute("http_request", arguments, context=context)
    return json.loads(raw)


def test_get_bounded(server: MockHTTP, reg: ToolRegistry) -> None:
    url = f"{server.base_url}/page"
    out = call_tool(reg, {"url": url}, context=url)
    check("GET 成功标识", out["type"] == "http_request_result", str(out.get("type")))
    check("状态 200", out["status"] == 200, str(out.get("status")))
    check("正文非空", bool(out["content"]), repr(out["content"][:30]))
    check("有界输出", out["end_index"] - out["start_index"] == len(out["content"]))
    check("长文 has_more", out["has_more"] is True, str(out.get("has_more")))
    check("total 大于切片", out["total_length"] > len(out["content"]))


def test_continuation(server: MockHTTP, reg: ToolRegistry) -> None:
    url = f"{server.base_url}/page"
    ctx = url
    first = call_tool(reg, {"url": url, "max_length": 2000}, context=ctx)
    e1 = first["end_index"]
    total = first["total_length"]
    check("首片非空", bool(first["content"]))
    second = call_tool(reg, {"url": url, "max_length": 2000, "start_index": e1}, context=ctx)
    check("续读推进 end_index", second["end_index"] > e1, f"{second['end_index']} vs {e1}")
    check("续读内容与首片不同", second["content"] != first["content"])
    check("total 稳定", second["total_length"] == total)
    check("无越界", second["end_index"] <= total)
    # 从头重读（start_index=0）应重新请求，切片从 0 开始
    again = call_tool(reg, {"url": url, "max_length": 2000}, context=ctx)
    check("从头重读回到 0", again["start_index"] == 0 and again["content"] == first["content"])


def test_raw(server: MockHTTP, reg: ToolRegistry) -> None:
    url = f"{server.base_url}/raw"
    out = call_tool(reg, {"url": url, "raw": True}, context=url)
    check("raw 返回原始文本", out["content"].startswith("<html>"), repr(out["content"][:20]))


def test_post(server: MockHTTP, reg: ToolRegistry) -> None:
    url = f"{server.base_url}/api"
    out = call_tool(reg, {"url": url, "method": "POST", "body": {"a": 1}}, context=url)
    check("POST 成功标识", out["type"] == "http_request_result", str(out.get("type")))
    check("状态 200", out["status"] == 200, str(out.get("status")))
    parsed = json.loads(out["content"])
    check("方法回显", parsed.get("method") == "POST", repr(parsed))
    check("请求体回显", parsed.get("body") == '{"a": 1}', repr(parsed.get("body")))


def test_404(server: MockHTTP, reg: ToolRegistry) -> None:
    url = f"{server.base_url}/nope"
    out = call_tool(reg, {"url": url}, context=url)
    check("404 降级为错误", out["type"] == "http_request_error", str(out.get("type")))
    check("错误含 HTTP 404", "404" in out["error"], repr(out.get("error")))


def test_url_rule(server: MockHTTP, reg: ToolRegistry) -> None:
    url = f"{server.base_url}/page"
    # host 未出现在对话 → 拒绝
    out = call_tool(reg, {"url": url}, context="一段与 URL 无关的对话内容")
    check("host 未出现 → 拒绝", out["type"] == "http_request_error", str(out.get("type")))
    check("拒绝提示", "未在对话中出现" in out["error"], repr(out.get("error")))
    # host 出现在对话 → 放行（软校验：提过一次即可）
    out2 = call_tool(reg, {"url": url}, context="用户提到想看看 127.0.0.1 的内容")
    check("host 出现 → 放行", out2["type"] == "http_request_result", str(out2.get("type")))


def test_method_whitelist(server: MockHTTP, reg: ToolRegistry) -> None:
    url = f"{server.base_url}/page"
    out = call_tool(reg, {"url": url, "method": "TRACE"}, context=url)
    check("非法方法被拒", out["type"] == "http_request_error", str(out.get("type")))
    check("提示不支持", "不支持的方法" in out["error"], repr(out.get("error")))


def test_scheme_whitelist(server: MockHTTP, reg: ToolRegistry) -> None:
    out = call_tool(reg, {"url": "ftp://example.com/x"}, context="ftp://example.com/x")
    check("非法协议被拒", out["type"] == "http_request_error", str(out.get("type")))
    check("提示仅支持", "仅支持 http/https" in out["error"], repr(out.get("error")))


def test_session(server: MockHTTP, reg: ToolRegistry) -> None:
    url = f"{server.base_url}/cookie"
    from aris.core import call

    # 无 session：每次新连接，cookie 不共享
    r1 = call("http.request", "GET", url)
    r2 = call("http.request", "GET", url)
    check("无会话不共享 cookie", "sid=abc123" not in r1.text and "sid=abc123" not in r2.text)
    # 命名会话：cookie 连续（第一次 Set-Cookie，第二次带回）
    s1 = call("http.request", "GET", url, session="tsess")
    s2 = call("http.request", "GET", url, session="tsess")
    check("命名会话 cookie 连续", "sid=abc123" in s2.text, repr(s2.text))
    check("首次访问无 cookie", "cookie=" in s1.text, repr(s1.text))


def main() -> None:
    server = MockHTTP().start()
    reg = make_registry()
    tests = [
        test_get_bounded,
        test_continuation,
        test_raw,
        test_post,
        test_404,
        test_url_rule,
        test_method_whitelist,
        test_scheme_whitelist,
        test_session,
    ]
    for t in tests:
        print(f"\n== {t.__name__}")
        try:
            t(server, reg)
        except Exception as e:  # noqa: BLE001
            global _fail
            _fail += 1
            print(f"  EXC   {type(e).__name__}: {e}")
    server.stop()
    print(f"\n----\nPASS {_pass} / FAIL {_fail}")


if __name__ == "__main__":
    main()