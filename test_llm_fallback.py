"""LLM fallback / 竞速 / 首字占位 全链路 mock 测试（无需真实 API key）。

本地跑流式 SSE mock 端点（mock_llm_server.py），构造多提供方配置直连，验证
engine.py 各行为：

- 阶段一 横向 fallback：正常流、可重试错误退避重试、重试耗尽切下家、
  不可重试（401）即切、中途已吐内容不切换
- 阶段二 模型级降级：主模型全灭后按 fallback_models 降级到备选模型
- 阶段三 竞速恢复：本家 vs 备选并发，微小差距（RACE_GRACE）内本家优先；
  本家过慢 / 立即失败时备选胜
- 首字占位：超时无产出先吐 stall 提示语，真实内容照常到达
- 全灭错误处理、无候选、退化单边竞速、思考链、sdk 传输直通、纯文本 stream()

运行：uv run python test_llm_fallback.py
"""

from __future__ import annotations

import os
import socket
import sys

from loguru import logger

logger.remove()
logger.add(sys.stderr, level="WARNING")

# 错误处理会广播桌面通知，测试里静音它
import aris.core.llm.notify as notify

notify.broadcast = lambda *a, **k: None  # noqa: E731

from mock_llm_server import (  # noqa: E402
    MockLLMServer,
    Scenario,
    content_chunk,
    finish_chunk,
    reasoning_chunk,
    tool_call_chunk,
)
from aris.core.llm.config import LLMModel, LLMProvider, ProviderConfig  # noqa: E402
from aris.core.llm.engine import LLMEngine  # noqa: E402
from aris.core.llm.message import ChatRequest, Message, MessageRole  # noqa: E402

STALL = 0.5           # 首字占位阈值（测试用，config 里默认 3.0）
ENGINE_TIMEOUT = 8.0  # 总体超时预算（测试充分大于各场景耗时，防卡死）
ERROR_MSG = "<预设错误提示语>"

_pass = 0
_fail = 0
_FAILED = []


# ---------------------------------------------------------------- 基础设施


def check(name: str, cond: bool, detail: str = "") -> None:
    """汇总断言：PASS/FAIL 计数。"""
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {name}")
    else:
        _fail += 1
        _FAILED.append(name)
        print(f"  FAIL  {name}  {detail}")


def make_req(model_id: str, text: str = "你好") -> ChatRequest:
    return ChatRequest(model_id=model_id, messages=[Message(role="user", content=text)])


def build_engine(server: MockLLMServer, specs: list[dict]) -> LLMEngine:
    """把规格列表构造成 ProviderConfig + LLMEngine（直连 mock，httpx 传输）。"""
    providers: list[LLMProvider] = []
    for ps in specs:
        pid = ps["id"]
        os.environ[f"{pid.upper()}_API_KEY"] = "mock-key"
        models = [
            LLMModel(
                id=m["id"],
                name=m["id"],
                request_name=m["id"],
                fallback_models=m.get("fallback_models", []),
                thinking_default=False,
            )
            for m in ps["models"]
        ]
        providers.append(
            LLMProvider(
                id=pid,
                name=pid,
                base_url=ps.get("base_url") or server.base_url(pid),
                api_key_env=f"{pid.upper()}_API_KEY",
                timeout=ps.get("timeout", 2.0),
                transport=ps.get("transport", "httpx"),
                connect_timeout=ps.get("connect_timeout", 1.0),
                retry_count=ps.get("retry_count", 1),
                backoff_base=ps.get("backoff_base", 0.05),
                race_fallback=ps.get("race_fallback", True),
                models=models,
            )
        )
    engine = LLMEngine(
        ProviderConfig(
            providers=providers,
            order=[ps["id"] for ps in specs],
            default_model=specs[0]["models"][0]["id"],
        ),
        timeout=ENGINE_TIMEOUT,
        first_token_stall=STALL,
        error_message=ERROR_MSG,
    )
    return engine


def model_id_hint(ps: dict) -> str:
    return ps["models"][0]["id"]


def register(server: MockLLMServer, pid: str, model: str, **kw) -> None:
    """注册场景并同时提供 chunks/finish 默认值。"""
    sc = Scenario(
        chunks=kw.pop("chunks", ["你好", ",", "Aris"]),
        finish_reason=kw.pop("finish_reason", "stop"),
        **kw,
    )
    server.register(sc, pid=pid, model=model)


# 单场景一次 server/engine，跑测试函数后汇总


def new_server():
    return MockLLMServer().start()


# ---------------------------------------------------------------- 测试场景


def t_happy() -> None:
    """正常流：文本+完成事件，标记实际模型，不降级无占位。"""
    server = new_server()
    register(server, "t1a", "m1")
    engine = build_engine(server, [{"id": "t1a", "models": [{"id": "m1"}]}])
    deltas = list(engine.stream_deltas(make_req("m1")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    check("happy 文本完整", text == "你好,Aris", repr(text))
    finishes = [d for d in deltas if d.finish_reason]
    check("happy 有完成事件", len(finishes) == 1)
    f = finishes[0]
    check("happy 完成事件带模型", f.model_id == "m1", repr(f))
    check("happy 未降级", not f.degraded)
    check("happy 无 stall", not any(d.stall for d in deltas))
    server.stop()


def t_stall() -> None:
    """首字占位：超过阈值仍无产出先吐预设提示语，真实内容照常到达。"""
    server = new_server()
    register(server, "t2a", "m1", first_delay=0.9)  # 首字 0.9s > STALL=0.5
    engine = build_engine(server, [{"id": "t2a", "models": [{"id": "m1"}]}])
    deltas = list(engine.stream_deltas(make_req("m1")))
    stalls = [d for d in deltas if d.stall]
    check("stall 恰好一次", len(stalls) == 1, str(len(stalls)))
    check("stall 内容为预设提示语", stalls and stalls[0].content == ERROR_MSG, repr(stalls[0].content if stalls else None))
    check("stall 先于真实内容", len(deltas) > 1 and deltas[0].stall, str(deltas))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    check("stall 后真实内容完整", text == "你好,Aris", repr(text))
    server.stop()


def t_retry_success() -> None:
    """可重试错误退避后同家重试成功（retry_count=1）。"""
    server = new_server()
    register(server, "t3a", "m1", errors=[429])
    engine = build_engine(server, [{"id": "t3a", "models": [{"id": "m1"}]}])
    deltas = list(engine.stream_deltas(make_req("m1")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    check("429 重试后文本完整", text == "你好,Aris", repr(text))
    check("429 请求两次", server.request_count("t3a", "m1") == 2, str(server.request_count("t3a", "m1")))
    server.stop()


def t_500_x2_switch() -> None:
    """重试耗尽（500 两次）切下家；下家同模型健康恢复。"""
    server = new_server()
    register(server, "t4a", "m1", errors=[500, 500])
    register(server, "t4b", "m1", chunks=["来自", "B"])
    engine = build_engine(server, [
        {"id": "t4a", "models": [{"id": "m1"}]},
        {"id": "t4b", "models": [{"id": "m1"}]},
    ])
    deltas = list(engine.stream_deltas(make_req("m1")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    check("500x2 后切到 B", text == "来自B", repr(text))
    check("A 请求恰两次（重试耗尽）", server.request_count("t4a", "m1") == 2, str(server.request_count("t4a", "m1")))
    check("B 请求一次", server.request_count("t4b", "m1") == 1)
    finishes = [d for d in deltas if d.finish_reason]
    check("切家不降级", finishes and finishes[0].degraded is False, repr(finishes[0] if finishes else None))
    server.stop()


def t_auth_no_retry() -> None:
    """不可重试错误（401）不重试直接切下家。"""
    server = new_server()
    register(server, "t5a", "m1", errors=[401])
    register(server, "t5b", "m1", chunks=["来自", "B"])
    engine = build_engine(server, [
        {"id": "t5a", "models": [{"id": "m1"}]},
        {"id": "t5b", "models": [{"id": "m1"}]},
    ])
    deltas = list(engine.stream_deltas(make_req("m1")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    check("401 切到 B", text == "来自B", repr(text))
    check("A 仅请求一次（不重试）", server.request_count("t5a", "m1") == 1, str(server.request_count("t5a", "m1")))
    server.stop()


def t_model_degrade() -> None:
    """主模型全灭 → 按 fallback_models 降级到备选模型（跨提供方）。"""
    server = new_server()
    register(server, "t6a", "m1", errors=[500, 500])
    register(server, "t6b", "m2", chunks=["这是", "降级模型"])
    engine = build_engine(server, [
        {"id": "t6a", "models": [{"id": "m1", "fallback_models": ["m2"]}]},
        {"id": "t6b", "models": [{"id": "m2"}]},
    ])
    deltas = list(engine.stream_deltas(make_req("m1")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    check("降级后文本来自 m2", text == "这是降级模型", repr(text))
    finishes = [d for d in deltas if d.finish_reason]
    f = finishes[0] if finishes else None
    check("降级完成事件带模型 m2", f is not None and f.model_id == "m2", repr(f))
    check("降级标记 degraded", f is not None and f.degraded, repr(f))
    check("可竞速（race_fallback）", f is not None and f.race_possible, repr(f))
    server.stop()


def t_race_home_wins() -> None:
    """竞速：备选先出首字但本家在其后 RACE_GRACE 内跟上 → 本家胜。"""
    server = new_server()
    register(server, "t7a", "home", first_delay=0.15, chunks=["本家", "回答"])
    register(server, "t7b", "fb", first_delay=0.05, chunks=["备选", "更快"])
    engine = build_engine(server, [
        {"id": "t7a", "models": [{"id": "home"}]},
        {"id": "t7b", "models": [{"id": "fb"}]},
    ])
    deltas = list(engine.stream_deltas_race(make_req("home"), make_req("fb")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    check("微小差距本家胜（文本来自本家）", text == "本家回答", repr(text))
    finishes = [d for d in deltas if d.finish_reason]
    f = finishes[0] if finishes else None
    check("胜者为本家模型", f is not None and f.model_id == "home", repr(f))
    check("本家胜不降级", f is not None and not f.degraded, repr(f))
    server.stop()


def t_race_fallback_wins() -> None:
    """竞速：本家过慢（超过 grace 窗口）→ 备选胜并标记降级 / 可竞速。"""
    server = new_server()
    register(server, "t8a", "home", first_delay=1.0, chunks=["本家", "太慢"])
    register(server, "t8b", "fb", first_delay=0.05, chunks=["备选", "先到"])
    engine = build_engine(server, [
        {"id": "t8a", "models": [{"id": "home"}]},
        {"id": "t8b", "models": [{"id": "fb"}]},
    ])
    deltas = list(engine.stream_deltas_race(make_req("home"), make_req("fb")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    check("本家过慢备选胜（文本来自备选）", text == "备选先到", repr(text))
    finishes = [d for d in deltas if d.finish_reason]
    f = finishes[0] if finishes else None
    check("胜者为备选模型", f is not None and f.model_id == "fb", repr(f))
    check("备选胜标记 degraded", f is not None and f.degraded, repr(f))
    check("备选胜可竞速", f is not None and f.race_possible, repr(f))
    server.stop()


def t_race_home_error() -> None:
    """竞速：本家立即失败，备选健康 → 备选胜。"""
    server = new_server()
    register(server, "t9a", "home", errors=[500])
    register(server, "t9b", "fb", chunks=["只有", "备选"])
    engine = build_engine(server, [
        {"id": "t9a", "models": [{"id": "home"}]},
        {"id": "t9b", "models": [{"id": "fb"}]},
    ])
    deltas = list(engine.stream_deltas_race(make_req("home"), make_req("fb")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    check("本家失败备选兜底", text == "只有备选", repr(text))
    finishes = [d for d in deltas if d.finish_reason]
    f = finishes[0] if finishes else None
    check("兜底标记降级", f is not None and f.degraded, repr(f))
    server.stop()


def t_all_fail() -> None:
    """全灭：无降级目标 → 错误处理返回预设提示语（不发完成事件）。"""
    server = new_server()
    register(server, "t10a", "m1", errors=[500, 500])
    engine = build_engine(server, [{"id": "t10a", "models": [{"id": "m1"}]}])
    deltas = list(engine.stream_deltas(make_req("m1")))
    check("无完成事件", not any(d.finish_reason for d in deltas))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    check("返回预设提示语", text == ERROR_MSG, repr(text))
    server.stop()


def t_mid_stream_fail() -> None:
    """中途已输出内容后失败：不再切换下家，直接错误处理。"""
    server = new_server()
    register(server, "t11a", "m1", chunks=["说了一半"], chunk_delay=3.0)  # 首字后挂起 → 读超时
    register(server, "t11b", "m1", chunks=["不该到", "这里"])
    engine = build_engine(server, [
        {"id": "t11a", "models": [{"id": "m1"}]},
        {"id": "t11b", "models": [{"id": "m1"}]},
    ])
    deltas = list(engine.stream_deltas(make_req("m1")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    check("保留已吐内容", "说了一半" in text, repr(text))
    check("含错误提示语", ERROR_MSG in text, repr(text))
    check("B 未被调用（不切换）", server.request_count("t11b", "m1") == 0, str(server.request_count("t11b", "m1")))
    check("无完成事件", not any(d.finish_reason for d in deltas))
    server.stop()


def t_network_fallback() -> None:
    """建连失败（连接拒绝）→ 重试耗尽切下家。"""
    # 先占一个临时端口再释放，确保端口上没有服务 → ConnectError
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    dead_port = probe.getsockname()[1]
    probe.close()
    server = new_server()
    register(server, "t12b", "m1", chunks=["网络", "兜底"])
    engine = build_engine(server, [
        {"id": "t12a", "models": [{"id": "m1"}], "base_url": f"http://127.0.0.1:{dead_port}/prov/t12a"},
        {"id": "t12b", "models": [{"id": "m1"}]},
    ])
    deltas = list(engine.stream_deltas(make_req("m1")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    check("连接拒绝切换成功", text == "网络兜底", repr(text))
    check("B 请求一次", server.request_count("t12b", "m1") == 1, str(server.request_count("t12b", "m1")))
    server.stop()


def t_no_candidate() -> None:
    """没有任何提供方支持该模型 → 错误处理。"""
    server = new_server()
    engine = build_engine(server, [{"id": "t13a", "models": [{"id": "m1"}]}])
    deltas = list(engine.stream_deltas(make_req("ghost")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    check("无候选返回预设提示语", text == ERROR_MSG, repr(text))
    server.stop()


def t_race_single_side() -> None:
    """竞速退化：备选无提供方 → 单边串行（保持正常流语义）。"""
    server = new_server()
    register(server, "t14a", "home", chunks=["单边", "回答"])
    engine = build_engine(server, [
        {"id": "t14a", "models": [{"id": "home"}]},
        {"id": "t14b", "models": [{"id": "other"}]},
    ])
    deltas = list(engine.stream_deltas_race(make_req("home"), make_req("ghost")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    check("单边串行文本正常", text == "单边回答", repr(text))
    finishes = [d for d in deltas if d.finish_reason]
    f = finishes[0] if finishes else None
    check("单边不降级", f is not None and not f.degraded and f.model_id == "home", repr(f))
    server.stop()


def t_thinking() -> None:
    """思考链增量透传。"""
    server = new_server()
    server.register(
        Scenario(thinking=["思考", "过程"], chunks=["结论"], first_delay=0.1),
        pid="t15a",
        model="m1",
    )
    engine = build_engine(server, [{"id": "t15a", "models": [{"id": "m1"}]}])
    deltas = list(engine.stream_deltas(make_req("m1")))
    reasoning = "".join(d.reasoning for d in deltas)
    check("思考链完整", reasoning == "思考过程", repr(reasoning))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    check("正文仍完整", text == "结论", repr(text))
    server.stop()


def t_sdk_transport() -> None:
    """sdk 传输直通 mock（结构化超时 / max_retries 不破坏 SDK 路径）。"""
    server = new_server()
    register(server, "t16a", "m1")
    engine = build_engine(server, [{"id": "t16a", "models": [{"id": "m1"}], "transport": "sdk"}])
    deltas = list(engine.stream_deltas(make_req("m1")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    check("sdk 直通文本完整", text == "你好,Aris", repr(text))
    finishes = [d for d in deltas if d.finish_reason]
    check("sdk 有完成事件", len(finishes) == 1)
    server.stop()


def t_plain_stream() -> None:
    """stream() 纯文本过滤：不泄漏 stall / 完成事件。"""
    server = new_server()
    register(server, "t17a", "m1", first_delay=0.9)
    engine = build_engine(server, [{"id": "t17a", "models": [{"id": "m1"}]}])
    text = "".join(engine.stream(make_req("m1")))
    check("stream() 只出真实文本", text == "你好,Aris", repr(text))
    server.stop()


def t_tool_calls() -> None:
    """工具调用流：分片拼装 + 完成事件带 tool_calls。"""
    server = new_server()
    server.register(
        Scenario(
            tool_calls=[
                tool_call_chunk(0, "call_1", "get_time", '{"year":'),
                tool_call_chunk(0, "call_1", "get_time", '2026}'),
            ],
            finish_reason="tool_calls",
        ),
        pid="t18a",
        model="m1",
    )
    engine = build_engine(server, [{"id": "t18a", "models": [{"id": "m1"}]}])
    deltas = list(engine.stream_deltas(make_req("m1")))
    finishes = [d for d in deltas if d.finish_reason]
    check("工具流完成事件", len(finishes) == 1)
    f = finishes[0]
    check("finish_reason 为 tool_calls", f.finish_reason == "tool_calls", repr(f.finish_reason))
    check("参数分片拼装为 dict", f.tool_calls and f.tool_calls[0].arguments == {"year": 2026}, repr(f.tool_calls))
    check("完成事件带模型", f.model_id == "m1", repr(f))
    server.stop()


# ---------------------------------------------------------------- 兜底清理


# ---------------------------------------------------------------- 入口

_TESTS = [
    t_happy,
    t_stall,
    t_retry_success,
    t_500_x2_switch,
    t_auth_no_retry,
    t_model_degrade,
    t_race_home_wins,
    t_race_fallback_wins,
    t_race_home_error,
    t_all_fail,
    t_mid_stream_fail,
    t_network_fallback,
    t_no_candidate,
    t_race_single_side,
    t_thinking,
    t_sdk_transport,
    t_plain_stream,
    t_tool_calls,
]


def main() -> int:
    for test in _TESTS:
        name = test.__name__.replace("t_", "")
        print(f"== {name} ==")
        try:
            test()
        except Exception as e:  # noqa: BLE001 —— 测试内部失败也要计数
            import traceback

            traceback.print_exc()
            check(name, False, f"异常: {e}")
    print("-" * 50)
    print(f"PASS {_pass} / FAIL {_fail}")
    if _FAILED:
        print("失败项:", ", ".join(_FAILED))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())