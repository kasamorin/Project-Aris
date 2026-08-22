"""mock LLM 端点：OpenAI Chat Completions 兼容的流式 SSE 服务器（测试用）。

按 (provider_id, model) 配置行为场景，覆盖 engine 各路径：

- errors：依次返回的错误状态码序列（[429]/[500]/[401]...），耗尽后恢复正常——
  用于测「重试退避 / 切下家 / 不可重试即切」
- first_delay：首字前的阻塞秒数——用于测「首字占位 stall」
- chunk_delay：chunk 之间的间隔秒数——也用于模拟「中途挂起」触发读超时
- chunks / thinking：文本与思考链分片
- tool_calls：工具调用增量（逐条独立 delta，可带索引分片）
- finish_reason：流结束原因（默认 stop）

线程安全：每请求独立线程处理（ThreadingHTTPServer），错误序列与请求计数加锁。

无场景注册的 (provider_id, model) 走默认场景（空文本、正常结束）。
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# ---------------------------------------------------------------- SSE 组装工具


def _delta(content: str = "", reasoning: str = "", tool_calls=None, finish_reason=None) -> dict:
    """构造一条 OpenAI chat 风格 SSE 增量。"""
    obj: dict = {"choices": [{"delta": {}, "finish_reason": finish_reason}]}
    d = obj["choices"][0]["delta"]
    if content:
        d["content"] = content
    if reasoning:
        d["reasoning_content"] = reasoning
    if tool_calls:
        d["tool_calls"] = tool_calls
    return obj


def content_chunk(text: str) -> dict:
    """普通文本增量。"""
    return _delta(content=text)


def reasoning_chunk(text: str) -> dict:
    """思考链增量。"""
    return _delta(reasoning=text)


def finish_chunk(reason: str = "stop") -> dict:
    """流结束增量（完成事件）。"""
    return _delta(finish_reason=reason)


def tool_call_chunk(idx: int, call_id: str, name: str, arguments: str) -> dict:
    """一条工具调用片段（arguments 为 JSON 字符串，可分片按 index 拼装）。
    注意返回的是「fragment」而非完整 SSE delta，服务端套 _delta 时再包成 list。
    """
    return {
        "index": idx,
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


# ---------------------------------------------------------------- 场景定义


@dataclass
class Scenario:
    """一个 (provider_id, model) 的行为描述。"""

    errors: list[int] = field(default_factory=list)  # 依次返回的错误状态码，耗尽恢复正常
    first_delay: float = 0.0       # 首字前阻塞秒数（测 stall）
    chunk_delay: float = 0.0       # chunk 间阻塞秒数（测慢流 / 中途挂起）
    chunks: list[str] = field(default_factory=list)  # 文本分片
    thinking: list[str] = field(default_factory=list)  # 思考链分片
    tool_calls: list[dict] = field(default_factory=list)  # 工具调用增量（含 finish_reason 用它）
    finish_reason: str = "stop"


# ---------------------------------------------------------------- HTTP 处理器


class _Handler(BaseHTTPRequestHandler):
    """处理 POST /prov/<provider_id>/chat/completions。"""

    protocol_version = "HTTP/1.0"
    server_version = "MockLLM/1.0"

    def log_message(self, *args: Any) -> None:  # 静默，避免测试刷屏
        pass

    # ---- 请求处理 ----

    def do_GET(self) -> None:
        mock: MockLLMServer = self.server.mock
        parts = self.path.split("/")
        if len(parts) >= 4 and parts[1] == "prov" and parts[3] == "models":
            self._send_models(parts[2])
            return
        self._send_error(404)

    def do_POST(self) -> None:
        mock: MockLLMServer = self.server.mock
        body = self._read_body()
        model = str(body.get("model", "?")) if isinstance(body, dict) else "?"
        pid = self._route_provider()

        scenario = mock.scenario_for(pid, model)
        mock.count_request(pid, model)

        with mock.lock:
            if scenario.errors:
                status = int(scenario.errors.pop(0))
            else:
                status = None
        if status is not None:
            self._send_error(status)
            return

        self._stream(scenario)

    # ---- 内部 ----

    def _send_models(self, pid: str) -> None:
        mock: MockLLMServer = self.server.mock
        data = [
            {"id": m, "object": "model", "created": 0, "owned_by": "mock"}
            for m in mock.models_for(pid)
        ]
        payload = json.dumps({"object": "list", "data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw or b"{}")
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _route_provider(self) -> str:
        parts = self.path.split("/")
        if len(parts) >= 3 and parts[1] == "prov":
            return parts[2]
        return "?"

    def _send_error(self, status: int) -> None:
        payload = json.dumps(
            {"error": {"message": f"mock error {status}", "type": "mock", "code": status}}
        ).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _stream(self, scenario: Scenario) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            if scenario.first_delay:
                time.sleep(scenario.first_delay)
            for frag in scenario.thinking:
                self._write_sse(json.dumps(_delta(reasoning=frag)))
                self._maybe_pause(scenario.chunk_delay)
            if scenario.tool_calls:
                for frag in scenario.tool_calls:
                    self._write_sse(json.dumps(_delta(tool_calls=[frag])))
                    self._maybe_pause(scenario.chunk_delay)
            else:
                for frag in scenario.chunks:
                    self._write_sse(json.dumps(_delta(content=frag)))
                    self._maybe_pause(scenario.chunk_delay)
            self._write_sse(json.dumps(_delta(finish_reason=scenario.finish_reason)))
            self._write_sse("[DONE]")
        finally:
            try:
                self.wfile.flush()
            except OSError:
                pass

    def _write_sse(self, payload: str) -> None:
        try:
            self.wfile.write(f"data: {payload}\n\n".encode())
            self.wfile.flush()
        except OSError:  # 客户端中途断开（读超时等）→ 安静退出
            pass

    def _maybe_pause(self, delay: float) -> None:
        if delay:
            time.sleep(delay)


# ---------------------------------------------------------------- 服务端


class MockLLMServer:
    """场景注册 + 请求计数 + 生命周期管理。"""

    def __init__(self) -> None:
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.mock = self
        self.lock = threading.Lock()
        self.scenarios: dict[tuple[str, str], Scenario] = {}
        self.counts: dict[tuple[str, str], int] = {}
        self.models: dict[str, list[str]] = {}
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True
        )

    def start(self) -> "MockLLMServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def base_url(self, provider_id: str) -> str:
        """某提供方应填的 base_url（transport 会再拼 /chat/completions）。"""
        return f"http://127.0.0.1:{self.port}/prov/{provider_id}"

    def register(self, scenario: Scenario, *, pid: str, model: str) -> None:
        """注册某提供方某模型的行为；model="*" 表示该提供方所有模型的兜底。"""
        with self.lock:
            self.scenarios[(pid, model)] = scenario

    def register_models(self, pid: str, models: list[str]) -> None:
        """注册某提供方 /models 返回的模型 id 列表。"""
        with self.lock:
            self.models[pid] = list(models)

    def models_for(self, pid: str) -> list[str]:
        with self.lock:
            return self.models.get(pid, [])

    def scenario_for(self, pid: str, model: str) -> Scenario:
        with self.lock:
            return (
                self.scenarios.get((pid, model))
                or self.scenarios.get((pid, "*"))
                or Scenario()
            )

    def count_request(self, pid: str, model: str) -> None:
        with self.lock:
            key = (pid, model)
            self.counts[key] = self.counts.get(key, 0) + 1

    def request_count(self, pid: str, model: str) -> int:
        with self.lock:
            return self.counts.get((pid, model), 0)

    def total_requests(self) -> int:
        with self.lock:
            return sum(self.counts.values())


# ---------------------------------------------------------------- CLI 独立运行


def main() -> None:
    """独立运行 mock 提供方，供 `aris llm test` / `aris chat` / `llm fetch` 真机验证。

    默认启动一个正常流式回复的提供方（pid=mock，模型 mock-model，端口 8765），
    可用参数覆盖为错误序列 / 首字延迟 / 慢流等场景。Ctrl+C 停止。
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="本地 mock LLM 提供方（OpenAI Chat Completions 兼容）"
    )
    parser.add_argument("--port", type=int, default=8765, help="监听端口（默认 8765）")
    parser.add_argument("--pid", default="mock", help="提供方 id（默认 mock）")
    parser.add_argument("--model", default="mock-model", help="响应模型 id（默认 mock-model）")
    parser.add_argument(
        "--models",
        default="mock-model",
        help="GET /models 返回的模型列表，逗号分隔（默认 mock-model）",
    )
    parser.add_argument("--errors", default="", help="依次返回的错误状态码，逗号分隔（如 429,500）")
    parser.add_argument("--first-delay", type=float, default=0.0, help="首字前阻塞秒数")
    parser.add_argument("--chunk-delay", type=float, default=0.0, help="chunk 间阻塞秒数")
    parser.add_argument("--text", default="你好，我是本地 mock 模型，LLM 链路正常。", help="回复文本")
    parser.add_argument("--thinking", default="", help="思考链文本（可选）")
    args = parser.parse_args()

    server = MockLLMServer()
    server.register_models(
        args.pid, [m.strip() for m in args.models.split(",") if m.strip()]
    )
    scenario = Scenario(
        errors=[int(e) for e in args.errors.split(",") if e.strip()],
        first_delay=args.first_delay,
        chunk_delay=args.chunk_delay,
        chunks=[args.text],
        thinking=[args.thinking] if args.thinking else [],
    )
    server.register(scenario, pid=args.pid, model=args.model)

    # 手动绑定指定端口（ThreadingHTTPServer 默认绑定 0 自动分配）
    server._httpd.server_close()
    from http.server import ThreadingHTTPServer as _T

    server._httpd = _T(("127.0.0.1", args.port), _Handler)
    server._httpd.mock = server
    server.port = args.port
    server._thread = threading.Thread(target=server._httpd.serve_forever, daemon=True)
    server.start()

    base = server.base_url(args.pid)
    print(f"mock 提供方启动: pid={args.pid}  base_url={base}")
    print(f"  /models: {server.models_for(args.pid)}")
    print(f"  场景: errors={scenario.errors} first_delay={args.first_delay} "
          f"chunk_delay={args.chunk_delay} thinking={bool(scenario.thinking)}")
    print("  测试: ARIS_LLM_PROVIDERS_FILE=config/providers.mock.toml "
          "uv run aris llm test --model %s" % args.model)
    print("  停止: Ctrl+C")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nmock 提供方已停止")
        server.stop()


if __name__ == "__main__":
    main()