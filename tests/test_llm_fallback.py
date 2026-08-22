"""LLM fallback / 竞速 / 首字占位 全链路 mock 测试（无需真实 API key）。

本地跑流式 SSE mock 端点（support.mock_llm_server），构造多提供方配置直连，
验证 engine.py 各行为：

- 横向 fallback：正常流、可重试错误退避重试、重试耗尽切下家、不可重试
  （401）即切、中途已吐内容不切换
- 模型级降级：主模型全灭后按 fallback_models 降级到备选模型
- 竞速恢复：本家 vs 备选并发，微小差距（RACE_GRACE）内本家优先；本家
  过慢 / 立即失败时备选胜
- 首字占位：超时无产出先吐 stall 提示语，真实内容照常到达
- 全灭错误处理、无候选、退化单边竞速、思考链、sdk 传输直通、纯文本 stream()

原根目录手写脚本迁移为 pytest（2026-08-18）。
"""

from __future__ import annotations

import socket

from support.helpers import (
    ERROR_MSG,
    build_engine,
    make_chat_request,
    register,
)
from support.mock_llm_server import MockLLMServer, Scenario, tool_call_chunk


def test_happy(llm_server: MockLLMServer) -> None:
    """正常流：文本+完成事件，标记实际模型，不降级无占位。

    first_token_stall 放宽（stall 行为由 test_stall 专门验证）：正常流只关注
    无降级/完成事件正常，避免 0.5s 阈值对首次连接的时序敏感偶发误报。
    """
    register(llm_server, "t1a", "m1")
    engine = build_engine(
        llm_server, [{"id": "t1a", "models": [{"id": "m1"}]}], first_token_stall=5.0
    )
    deltas = list(engine.stream_deltas(make_chat_request("m1")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    assert text == "你好,Aris", repr(text)
    finishes = [d for d in deltas if d.finish_reason]
    assert len(finishes) == 1
    f = finishes[0]
    assert f.model_id == "m1", repr(f)
    assert not f.degraded
    assert not any(d.stall for d in deltas)


def test_stall(llm_server: MockLLMServer) -> None:
    """首字占位：超过阈值仍无产出先吐预设提示语，真实内容照常到达。"""
    register(llm_server, "t2a", "m1", first_delay=0.9)  # 首字 0.9s > STALL=0.5
    engine = build_engine(llm_server, [{"id": "t2a", "models": [{"id": "m1"}]}])
    deltas = list(engine.stream_deltas(make_chat_request("m1")))
    stalls = [d for d in deltas if d.stall]
    assert len(stalls) == 1, str(len(stalls))
    assert stalls and stalls[0].content == ERROR_MSG, repr(stalls[0].content if stalls else None)
    assert len(deltas) > 1 and deltas[0].stall, str(deltas)
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    assert text == "你好,Aris", repr(text)


def test_retry_success(llm_server: MockLLMServer) -> None:
    """可重试错误退避后同家重试成功（retry_count=1）。"""
    register(llm_server, "t3a", "m1", errors=[429])
    engine = build_engine(llm_server, [{"id": "t3a", "models": [{"id": "m1"}]}])
    deltas = list(engine.stream_deltas(make_chat_request("m1")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    assert text == "你好,Aris", repr(text)
    assert llm_server.request_count("t3a", "m1") == 2, str(llm_server.request_count("t3a", "m1"))


def test_500_x2_switch(llm_server: MockLLMServer) -> None:
    """重试耗尽（500 两次）切下家；下家同模型健康恢复。"""
    register(llm_server, "t4a", "m1", errors=[500, 500])
    register(llm_server, "t4b", "m1", chunks=["来自", "B"])
    engine = build_engine(llm_server, [
        {"id": "t4a", "models": [{"id": "m1"}]},
        {"id": "t4b", "models": [{"id": "m1"}]},
    ])
    deltas = list(engine.stream_deltas(make_chat_request("m1")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    assert text == "来自B", repr(text)
    assert llm_server.request_count("t4a", "m1") == 2, str(llm_server.request_count("t4a", "m1"))
    assert llm_server.request_count("t4b", "m1") == 1
    finishes = [d for d in deltas if d.finish_reason]
    assert finishes and finishes[0].degraded is False, repr(finishes[0] if finishes else None)


def test_auth_no_retry(llm_server: MockLLMServer) -> None:
    """不可重试错误（401）不重试直接切下家。"""
    register(llm_server, "t5a", "m1", errors=[401])
    register(llm_server, "t5b", "m1", chunks=["来自", "B"])
    engine = build_engine(llm_server, [
        {"id": "t5a", "models": [{"id": "m1"}]},
        {"id": "t5b", "models": [{"id": "m1"}]},
    ])
    deltas = list(engine.stream_deltas(make_chat_request("m1")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    assert text == "来自B", repr(text)
    assert llm_server.request_count("t5a", "m1") == 1, str(llm_server.request_count("t5a", "m1"))


def test_model_degrade(llm_server: MockLLMServer) -> None:
    """主模型全灭 → 按 fallback_models 降级到备选模型（跨提供方）。"""
    register(llm_server, "t6a", "m1", errors=[500, 500])
    register(llm_server, "t6b", "m2", chunks=["这是", "降级模型"])
    engine = build_engine(llm_server, [
        {"id": "t6a", "models": [{"id": "m1", "fallback_models": ["m2"]}]},
        {"id": "t6b", "models": [{"id": "m2"}]},
    ])
    deltas = list(engine.stream_deltas(make_chat_request("m1")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    assert text == "这是降级模型", repr(text)
    finishes = [d for d in deltas if d.finish_reason]
    f = finishes[0] if finishes else None
    assert f is not None and f.model_id == "m2", repr(f)
    assert f is not None and f.degraded, repr(f)
    assert f is not None and f.race_possible, repr(f)


def test_race_home_wins(llm_server: MockLLMServer) -> None:
    """竞速：备选先出首字但本家在其后 RACE_GRACE 内跟上 → 本家胜。"""
    register(llm_server, "t7a", "home", first_delay=0.15, chunks=["本家", "回答"])
    register(llm_server, "t7b", "fb", first_delay=0.05, chunks=["备选", "更快"])
    engine = build_engine(llm_server, [
        {"id": "t7a", "models": [{"id": "home"}]},
        {"id": "t7b", "models": [{"id": "fb"}]},
    ])
    deltas = list(engine.stream_deltas_race(make_chat_request("home"), make_chat_request("fb")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    assert text == "本家回答", repr(text)
    finishes = [d for d in deltas if d.finish_reason]
    f = finishes[0] if finishes else None
    assert f is not None and f.model_id == "home", repr(f)
    assert f is not None and not f.degraded, repr(f)


def test_race_fallback_wins(llm_server: MockLLMServer) -> None:
    """竞速：本家过慢（超过 grace 窗口）→ 备选胜并标记降级 / 可竞速。"""
    register(llm_server, "t8a", "home", first_delay=1.0, chunks=["本家", "太慢"])
    register(llm_server, "t8b", "fb", first_delay=0.05, chunks=["备选", "先到"])
    engine = build_engine(llm_server, [
        {"id": "t8a", "models": [{"id": "home"}]},
        {"id": "t8b", "models": [{"id": "fb"}]},
    ])
    deltas = list(engine.stream_deltas_race(make_chat_request("home"), make_chat_request("fb")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    assert text == "备选先到", repr(text)
    finishes = [d for d in deltas if d.finish_reason]
    f = finishes[0] if finishes else None
    assert f is not None and f.model_id == "fb", repr(f)
    assert f is not None and f.degraded, repr(f)
    assert f is not None and f.race_possible, repr(f)


def test_race_home_error(llm_server: MockLLMServer) -> None:
    """竞速：本家立即失败，备选健康 → 备选胜。"""
    register(llm_server, "t9a", "home", errors=[500])
    register(llm_server, "t9b", "fb", chunks=["只有", "备选"])
    engine = build_engine(llm_server, [
        {"id": "t9a", "models": [{"id": "home"}]},
        {"id": "t9b", "models": [{"id": "fb"}]},
    ])
    deltas = list(engine.stream_deltas_race(make_chat_request("home"), make_chat_request("fb")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    assert text == "只有备选", repr(text)
    finishes = [d for d in deltas if d.finish_reason]
    f = finishes[0] if finishes else None
    assert f is not None and f.degraded, repr(f)


def test_all_fail(llm_server: MockLLMServer) -> None:
    """全灭：无降级目标 → 错误处理返回预设提示语（不发完成事件）。"""
    register(llm_server, "t10a", "m1", errors=[500, 500])
    engine = build_engine(llm_server, [{"id": "t10a", "models": [{"id": "m1"}]}])
    deltas = list(engine.stream_deltas(make_chat_request("m1")))
    assert not any(d.finish_reason for d in deltas)
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    assert text == ERROR_MSG, repr(text)


def test_mid_stream_fail(llm_server: MockLLMServer) -> None:
    """中途已输出内容后失败：不再切换下家，直接错误处理。"""
    register(llm_server, "t11a", "m1", chunks=["说了一半"], chunk_delay=3.0)  # 首字后挂起 → 读超时
    register(llm_server, "t11b", "m1", chunks=["不该到", "这里"])
    engine = build_engine(llm_server, [
        {"id": "t11a", "models": [{"id": "m1"}]},
        {"id": "t11b", "models": [{"id": "m1"}]},
    ])
    deltas = list(engine.stream_deltas(make_chat_request("m1")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    assert "说了一半" in text, repr(text)
    assert ERROR_MSG in text, repr(text)
    assert llm_server.request_count("t11b", "m1") == 0, str(llm_server.request_count("t11b", "m1"))
    assert not any(d.finish_reason for d in deltas)


def test_network_fallback(llm_server: MockLLMServer) -> None:
    """建连失败（连接拒绝）→ 重试耗尽切下家。"""
    # 先占一个临时端口再释放，确保端口上没有服务 → ConnectError
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    dead_port = probe.getsockname()[1]
    probe.close()
    register(llm_server, "t12b", "m1", chunks=["网络", "兜底"])
    engine = build_engine(llm_server, [
        {"id": "t12a", "models": [{"id": "m1"}], "base_url": f"http://127.0.0.1:{dead_port}/prov/t12a"},
        {"id": "t12b", "models": [{"id": "m1"}]},
    ])
    deltas = list(engine.stream_deltas(make_chat_request("m1")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    assert text == "网络兜底", repr(text)
    assert llm_server.request_count("t12b", "m1") == 1, str(llm_server.request_count("t12b", "m1"))


def test_no_candidate(llm_server: MockLLMServer) -> None:
    """没有任何提供方支持该模型 → 错误处理。"""
    engine = build_engine(llm_server, [{"id": "t13a", "models": [{"id": "m1"}]}])
    deltas = list(engine.stream_deltas(make_chat_request("ghost")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    assert text == ERROR_MSG, repr(text)


def test_race_single_side(llm_server: MockLLMServer) -> None:
    """竞速退化：备选无提供方 → 单边串行（保持正常流语义）。"""
    register(llm_server, "t14a", "home", chunks=["单边", "回答"])
    engine = build_engine(llm_server, [
        {"id": "t14a", "models": [{"id": "home"}]},
        {"id": "t14b", "models": [{"id": "other"}]},
    ])
    deltas = list(engine.stream_deltas_race(make_chat_request("home"), make_chat_request("ghost")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    assert text == "单边回答", repr(text)
    finishes = [d for d in deltas if d.finish_reason]
    f = finishes[0] if finishes else None
    assert f is not None and not f.degraded and f.model_id == "home", repr(f)


def test_thinking(llm_server: MockLLMServer) -> None:
    """思考链增量透传。"""
    llm_server.register(
        Scenario(thinking=["思考", "过程"], chunks=["结论"], first_delay=0.1),
        pid="t15a",
        model="m1",
    )
    engine = build_engine(llm_server, [{"id": "t15a", "models": [{"id": "m1"}]}])
    deltas = list(engine.stream_deltas(make_chat_request("m1")))
    reasoning = "".join(d.reasoning for d in deltas)
    assert reasoning == "思考过程", repr(reasoning)
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    assert text == "结论", repr(text)


def test_sdk_transport(llm_server: MockLLMServer) -> None:
    """sdk 传输直通 mock（结构化超时 / max_retries 不破坏 SDK 路径）。"""
    register(llm_server, "t16a", "m1")
    engine = build_engine(llm_server, [{"id": "t16a", "models": [{"id": "m1"}], "transport": "sdk"}])
    deltas = list(engine.stream_deltas(make_chat_request("m1")))
    text = "".join(d.content for d in deltas if d.content and not d.stall)
    assert text == "你好,Aris", repr(text)
    finishes = [d for d in deltas if d.finish_reason]
    assert len(finishes) == 1


def test_plain_stream(llm_server: MockLLMServer) -> None:
    """stream() 纯文本过滤：不泄漏 stall / 完成事件。"""
    register(llm_server, "t17a", "m1", first_delay=0.9)
    engine = build_engine(llm_server, [{"id": "t17a", "models": [{"id": "m1"}]}])
    text = "".join(engine.stream(make_chat_request("m1")))
    assert text == "你好,Aris", repr(text)


def test_tool_calls(llm_server: MockLLMServer) -> None:
    """工具调用流：分片拼装 + 完成事件带 tool_calls。"""
    llm_server.register(
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
    engine = build_engine(llm_server, [{"id": "t18a", "models": [{"id": "m1"}]}])
    deltas = list(engine.stream_deltas(make_chat_request("m1")))
    finishes = [d for d in deltas if d.finish_reason]
    assert len(finishes) == 1
    f = finishes[0]
    assert f.finish_reason == "tool_calls", repr(f.finish_reason)
    assert f.tool_calls and f.tool_calls[0].arguments == {"year": 2026}, repr(f.tool_calls)
    assert f.model_id == "m1", repr(f)
