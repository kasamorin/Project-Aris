"""单 provider 脚本化 mock：按请求序号驱动不同场景，外围功能零 API 全覆盖。

用户场景：真实提供方只有一个且并发受限，无法批量实测外围功能。改为在
mock 上注册「脚本序列」——同一 (provider_id, model) 的第 1 次请求测
功能 A、第 2 次请求测功能 B……既跑通外围链路，又不花 API、延迟低。

覆盖两条外围链路：
- 连续多轮对话：第 1/2/3 次请求依次返回不同脚本文本（验证按请求分步）
- 工具往返：第 1 次请求回 tool_calls → loop 执行工具并回填 → 第 2 次
  请求回最终回答（验证流式拼装 + 工具执行 + 结果回填闭环）
"""

from __future__ import annotations

from aris.behavior import AgentLoop, LoopEventType, ToolRegistry
from aris.chat.session import ChatSession

from support.helpers import build_engine, events_of, user_messages
from support.mock_llm_server import MockLLMServer, Scenario, tool_call_chunk


def test_scripted_sequence_answers(llm_server: MockLLMServer) -> None:
    """同一 provider 连续 3 次请求依次响应 3 个脚本场景。"""
    llm_server.register_script(
        [
            Scenario(chunks=["第一回合"]),
            Scenario(chunks=["第二回合", "-B"]),
            Scenario(chunks=["第三回合"]),
        ],
        pid="s1a",
        model="m1",
    )
    engine = build_engine(llm_server, [{"id": "s1a", "models": [{"id": "m1"}]}])
    session = ChatSession(engine, model_id="m1", tools_enabled=False)

    assert "".join(session.ask("hi1")) == "第一回合"
    assert "".join(session.ask("hi2")) == "第二回合-B"
    assert "".join(session.ask("hi3")) == "第三回合"

    # 每个会话轮恰好一次 HTTP 请求 → 验证脚本按请求序号逐步消耗
    assert llm_server.request_count("s1a", "m1") == 3


def test_scripted_tool_roundtrip(llm_server: MockLLMServer) -> None:
    """脚本两步：第 1 次请求回 tool_calls，第 2 次请求回最终回答。

    一条 provider 上跑通「流式拼装 → 工具执行 → 结果回填 → 再请求」闭环。
    """
    llm_server.register_script(
        [
            Scenario(
                tool_calls=[
                    tool_call_chunk(0, "call_1", "echo", '{"text":"你好"}')
                ],
                finish_reason="tool_calls",
            ),
            Scenario(chunks=["收到，已完成"]),
        ],
        pid="s2a",
        model="m1",
    )
    engine = build_engine(llm_server, [{"id": "s2a", "models": [{"id": "m1"}]}])

    registry = ToolRegistry()
    registry.register(
        "echo",
        description="原样返回 text 参数",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        fn=lambda **kw: kw["text"],
    )
    loop = AgentLoop(engine, registry=registry, model_id="m1", max_rounds=2)

    events = events_of(loop, user_messages("m1"))

    tools = [e for e in events if e.type == LoopEventType.TOOL]
    assert len(tools) == 1, repr(tools)
    assert tools[0].name == "echo", repr(tools[0].name)
    assert tools[0].result == "你好", repr(tools[0].result)

    done = [e for e in events if e.type == LoopEventType.DONE][0]
    assert done.content == "收到，已完成", repr(done.content)

    # 工具往返恰好两次请求（tool_calls 轮 + 最终回答轮）
    assert llm_server.request_count("s2a", "m1") == 2


def test_scripted_exhaustion_falls_back(llm_server: MockLLMServer) -> None:
    """脚本耗尽后回退常规场景：第 3 次请求起走 register 的固定行为。"""
    llm_server.register_script(
        [
            Scenario(chunks=["脚本第一步"]),
            Scenario(errors=[500]),
        ],
        pid="s3a",
        model="m1",
    )
    llm_server.register(
        Scenario(chunks=["常规兜底"]), pid="s3a", model="m1"
    )
    engine = build_engine(llm_server, [{"id": "s3a", "models": [{"id": "m1"}]}])
    session = ChatSession(engine, model_id="m1", tools_enabled=False)

    assert "".join(session.ask("hi1")) == "脚本第一步"
    assert "".join(session.ask("hi2")) != ""
    assert "".join(session.ask("hi3")) == "常规兜底"
    assert "".join(session.ask("hi4")) == "常规兜底"