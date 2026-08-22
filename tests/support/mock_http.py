"""mock HTTP 端点（http_request 工具测试用，本地 ThreadingHTTPServer）。

路由覆盖 http_request 工具各路径：
- /page：长文 HTML（测有界输出 / has_more / start_index 续读）
- /raw：原始 HTML（测 raw=true 原文返回）
- /api：GET 返回 JSON、POST 回显请求体
- /cookie：无 Cookie 时 Set-Cookie，否则回显 Cookie（测命名会话连续）
- 其他路径：404（测宽容降级）
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
