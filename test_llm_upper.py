"""上层（loop / session）与 engine 的集成测试（复用 mock_llm_server）。

验证：
- loop.iter_events：STALL 事件独立产出、不并入最终回答；DONE 携带
  model_id / degraded / race_possible；race_model 竞速时备选胜标记降级
- session 降级恢复循环：降级后记住实际生效模型，下一轮竞速回主模型，
  恢复后退出降级模式；stall / degraded 回调可达

运行：uv run python test_llm_upper.py
"""

from __future__ import annotations

import os
import sys

from loguru import logger

logger.remove()
logger.add(sys.stderr, level="WARNING")

import aris.core.llm.notify as notify

notify.broadcast = lambda *a, **k: None  # noqa: E731
logger.remove()

from mock_llm_server import MockLLMServer, Scenario  # noqa: E402
from aris.behavior import AgentLoop, LoopEventType, ToolRegistry  # noqa: E402
from aris.chat.session import ChatSession  # noqa: E402
from aris.core.llm.config import LLMModel, LLMProvider, ProviderConfig  # noqa: E402
from aris.core.llm.engine import LLMEngine  # noqa: E402
from aris.core.llm.message import Message  # noqa: E402
from aris.core.llm.message import MessageRole

STALL = 0.5
ERROR_MSG = "<预设错误提示语>"

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


def register(server: MockLLMServer, pid: str, model: str, **kw) -> None:
    sc = Scenario(
        chunks=kw.pop("chunks", ["你好", ",", "Aris"]),
        finish_reason=kw.pop("finish_reason", "stop"),
        **kw,
    )
    server.register(sc, pid=pid, model=model)


def build_engine(server: MockLLMServer, specs: list[dict]) -> LLMEngine:
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
                base_url=server.base_url(pid),
                api_key_env=f"{pid.upper()}_API_KEY",
                timeout=2.0,
                transport="httpx",
                connect_timeout=1.0,
                retry_count=1,
                backoff_base=0.05,
                models=models,
            )
        )
    return LLMEngine(
        ProviderConfig(
            providers=providers,
            order=[ps["id"] for ps in specs],
            default_model=specs[0]["models"][0]["id"],
        ),
        timeout=8.0,
        first_token_stall=STALL,
        error_message=ERROR_MSG,
    )


def make_loop(engine: LLMEngine) -> AgentLoop:
    return AgentLoop(
        engine,
        registry=ToolRegistry(),
        model_id=engine.providers.default_model or "m1",
    )


def req(model_id: str, text: str = "你好") -> list[Message]:
    return [Message(role=MessageRole.USER, content=text)]


def events_of(loop: AgentLoop, messages: list[Message], **kw):
    return list(loop.iter_events(messages, **kw))


# ---------------------------------------------------------------- loop 层


def t_loop_stall() -> None:
    """首字慢：STALL 事件独立产出，不并入最终回答内容。"""
    server = MockLLMServer().start()
    register(server, "u1a", "m1", first_delay=0.9)
    engine = build_engine(server, [{"id": "u1a", "models": [{"id": "m1"}]}])
    loop = make_loop(engine)
    evs = events_of(loop, req("m1"))
    stalls = [e for e in evs if e.type == LoopEventType.STALL]
    check("loop 产出 STALL 一次", len(stalls) == 1, str(len(stalls)))
    check(
        "STALL 内容是预设提示语",
        stalls and stalls[0].content == ERROR_MSG,
        repr(stalls[0].content if stalls else None),
    )
    done = [e for e in evs if e.type == LoopEventType.DONE][0]
    check("最终回答不含占位文本", ERROR_MSG not in done.content, repr(done.content))
    check("回答内容完整", done.content == "你好,Aris", repr(done.content))
    check("DONE 带实际模型", done.model_id == "m1", repr(done.model_id))
    check("未降级", not done.degraded)
    server.stop()


def t_loop_race_fb_wins() -> None:
    """竞速：本家过慢 → 备选胜，DONE 标记降级与实际模型。"""
    server = MockLLMServer().start()
    register(server, "u2a", "m1", first_delay=1.0, chunks=["本家", "太慢"])
    register(server, "u2b", "m2", first_delay=0.05, chunks=["备选", "先到"])
    engine = build_engine(
        server,
        [
            {"id": "u2a", "models": [{"id": "m1"}]},
            {"id": "u2b", "models": [{"id": "m2"}]},
        ],
    )
    loop = make_loop(engine)
    evs = events_of(loop, req("m1"), race_model="m2")
    done = [e for e in evs if e.type == LoopEventType.DONE][0]
    check("备选胜：回答来自 m2", done.content == "备选先到", repr(done.content))
    check("DONE 模型为 m2", done.model_id == "m2", repr(done.model_id))
    check("标记降级", done.degraded)
    check("可竞速", done.race_possible)
    server.stop()


def t_loop_race_home_wins() -> None:
    """竞速：微小差距内本家跟上 → 本家胜，不降级。"""
    server = MockLLMServer().start()
    register(server, "u3a", "m1", first_delay=0.15, chunks=["本家", "回答"])
    register(server, "u3b", "m2", first_delay=0.05, chunks=["备选", "更快"])
    engine = build_engine(
        server,
        [
            {"id": "u3a", "models": [{"id": "m1"}]},
            {"id": "u3b", "models": [{"id": "m2"}]},
        ],
    )
    loop = make_loop(engine)
    evs = events_of(loop, req("m1"), race_model="m2")
    done = [e for e in evs if e.type == LoopEventType.DONE][0]
    check("本家胜：回答来自 m1", done.content == "本家回答", repr(done.content))
    check("DONE 模型为 m1", done.model_id == "m1", repr(done.model_id))
    check("未降级", not done.degraded)
    server.stop()


# ---------------------------------------------------------------- session 层


def t_session_cycle() -> None:
    """降级恢复循环：降级→记住模型→竞速回主模型→恢复后退出降级模式。"""

    server = MockLLMServer().start()
    register(server, "u4a", "m1", errors=[500, 500])  # 主模型故障
    register(server, "u4b", "m2", chunks=["降级回答"])
    engine = build_engine(
        server,
        [
            {"id": "u4a", "models": [{"id": "m1", "fallback_models": ["m2"]}]},
            {"id": "u4b", "models": [{"id": "m2"}]},
        ],
    )
    s = ChatSession(engine, model_id="m1", tools_enabled=False)

    # 第 1 轮：主模型故障，模型级降级到 m2
    texts1 = list(s.ask("hi"))
    check("第1轮回答来自降级模型", "".join(texts1) == "降级回答", repr("".join(texts1)))
    check("会话记住降级模型 m2", s._degraded_model == "m2", repr(s._degraded_model))

    # 第 2 轮：主模型恢复 → 竞速应让本家胜（健康），退出降级模式
    register(server, "u4a", "m1", first_delay=0.05, chunks=["主模型回复"])  # 覆盖为健康
    texts2 = list(s.ask("hi2"))
    check("第2轮竞速回主模型", "".join(texts2) == "主模型回复", repr("".join(texts2)))
    check("降级模式已退出", s._degraded_model is None, repr(s._degraded_model))

    # 第 3 轮：主模型再度故障 → 再次降级并记住
    register(server, "u4a", "m1", errors=[500, 500])
    texts3 = list(s.ask("hi3"))
    check("第3轮再度降级", "".join(texts3) == "降级回答", repr("".join(texts3)))
    check("重新记住降级模型", s._degraded_model == "m2", repr(s._degraded_model))
    server.stop()


def t_session_stall_cb() -> None:
    """stall 回调可达；回答文本不受占位污染。"""
    server = MockLLMServer().start()
    register(server, "u5a", "m1", first_delay=0.9)
    engine = build_engine(server, [{"id": "u5a", "models": [{"id": "m1"}]}])
    s = ChatSession(engine, model_id="m1", tools_enabled=False)
    stalls: list[str] = []
    texts = list(s.ask("hi", on_stall=stalls.append))
    reply = "".join(texts)
    check("回调收到 stall", len(stalls) == 1, str(len(stalls)))
    check("stall 内容为预设提示语", stalls and stalls[0] == ERROR_MSG, repr(stalls))
    check("回答不含占位文本", ERROR_MSG not in reply, repr(reply))
    server.stop()


def t_session_degraded_cb() -> None:
    """降级回调携带实际生效模型 id；无降级时不回调。"""
    server = MockLLMServer().start()
    register(server, "u6a", "m1", errors=[500, 500])
    register(server, "u6b", "m2", chunks=["降级回答"])
    engine = build_engine(
        server,
        [
            {"id": "u6a", "models": [{"id": "m1", "fallback_models": ["m2"]}]},
            {"id": "u6b", "models": [{"id": "m2"}]},
        ],
    )
    s = ChatSession(engine, model_id="m1", tools_enabled=False)
    degraded: list[str] = []
    list(s.ask("hi", on_degraded=degraded.append))
    check("降级回调收到实际模型", degraded == ["m2"], repr(degraded))
    server.stop()


def t_session_no_deg_no_cb() -> None:
    """主模型健康时不触发降级回调。"""
    server = MockLLMServer().start()
    register(server, "u7a", "m1", chunks=["正常回答"])
    engine = build_engine(server, [{"id": "u7a", "models": [{"id": "m1"}]}])
    s = ChatSession(engine, model_id="m1", tools_enabled=False)
    degraded: list[str] = []
    texts = list(s.ask("hi", on_degraded=degraded.append))
    check("回答正常", "".join(texts) == "正常回答", repr("".join(texts)))
    check("无降级回调", degraded == [], repr(degraded))
    check("退出降级模式", s._degraded_model is None)
    server.stop()


# ---------------------------------------------------------------- 入口


def main() -> None:
    tests = [
        t_loop_stall,
        t_loop_race_fb_wins,
        t_loop_race_home_wins,
        t_session_cycle,
        t_session_stall_cb,
        t_session_degraded_cb,
        t_session_no_deg_no_cb,
    ]
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