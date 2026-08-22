"""共享测试 helper：构造 mock 提供方配置与 agent 组件。

原根目录 test_llm_fallback.py / test_llm_upper.py 各有一份近似的
build_engine / register 实现，迁移为 pytest 时收口到这里取并集，避免重复。
"""

from __future__ import annotations

import os

from aris.behavior import AgentLoop, ToolRegistry
from aris.core.llm.config import LLMModel, LLMProvider, ProviderConfig
from aris.core.llm.engine import LLMEngine
from aris.core.llm.message import ChatRequest, Message, MessageRole

from support.mock_llm_server import MockLLMServer, Scenario

STALL = 0.5           # 首字占位阈值（测试用，config 里默认 3.0）
ENGINE_TIMEOUT = 8.0  # 总体超时预算（测试充分大于各场景耗时，防卡死）
ERROR_MSG = "<预设错误提示语>"


def build_engine(
    server: MockLLMServer,
    specs: list[dict],
    *,
    first_token_stall: float = STALL,
) -> LLMEngine:
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
    return LLMEngine(
        ProviderConfig(
            providers=providers,
            order=[ps["id"] for ps in specs],
            default_model=specs[0]["models"][0]["id"],
        ),
        timeout=ENGINE_TIMEOUT,
        first_token_stall=first_token_stall,
        error_message=ERROR_MSG,
    )


def register(server: MockLLMServer, pid: str, model: str, **kw) -> None:
    """注册场景并同时提供 chunks/finish 默认值。"""
    sc = Scenario(
        chunks=kw.pop("chunks", ["你好", ",", "Aris"]),
        finish_reason=kw.pop("finish_reason", "stop"),
        **kw,
    )
    server.register(sc, pid=pid, model=model)


def make_chat_request(model_id: str, text: str = "你好") -> ChatRequest:
    """构造 engine.stream_deltas 的入参（fallback 层测试用）。"""
    return ChatRequest(model_id=model_id, messages=[Message(role="user", content=text)])


def user_messages(model_id: str, text: str = "你好") -> list[Message]:
    """构造 loop 的入参消息列表（loop/session 层测试用）。"""
    return [Message(role=MessageRole.USER, content=text)]


def make_loop(engine: LLMEngine) -> AgentLoop:
    """构造默认 agent loop（空 registry + 默认模型）。"""
    return AgentLoop(
        engine,
        registry=ToolRegistry(),
        model_id=engine.providers.default_model or "m1",
    )


def events_of(loop: AgentLoop, messages: list[Message], **kw):
    """把 loop 事件流收集成列表。"""
    return list(loop.iter_events(messages, **kw))
