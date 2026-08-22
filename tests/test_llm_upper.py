"""上层（loop / session）与 engine 的集成测试（复用 support.mock_llm_server）。

验证：
- loop.iter_events：STALL 事件独立产出、不并入最终回答；DONE 携带
  model_id / degraded / race_possible；race_model 竞速时备选胜标记降级
- session 降级恢复循环：降级后记住实际生效模型，下一轮竞速回主模型，
  恢复后退出降级模式；stall / degraded 回调可达

原根目录手写脚本迁移为 pytest（2026-08-18）。
"""

from __future__ import annotations

from aris.behavior import LoopEventType
from aris.chat.session import ChatSession

from support.helpers import (
    ERROR_MSG,
    build_engine,
    events_of,
    make_loop,
    register,
    user_messages,
)
from support.mock_llm_server import MockLLMServer


def test_loop_stall(llm_server: MockLLMServer) -> None:
    """首字慢：STALL 事件独立产出，不并入最终回答内容。"""
    register(llm_server, "u1a", "m1", first_delay=0.9)
    engine = build_engine(llm_server, [{"id": "u1a", "models": [{"id": "m1"}]}])
    loop = make_loop(engine)
    evs = events_of(loop, user_messages("m1"))
    stalls = [e for e in evs if e.type == LoopEventType.STALL]
    assert len(stalls) == 1, str(len(stalls))
    assert stalls and stalls[0].content == ERROR_MSG, repr(stalls[0].content if stalls else None)
    done = [e for e in evs if e.type == LoopEventType.DONE][0]
    assert ERROR_MSG not in done.content, repr(done.content)
    assert done.content == "你好,Aris", repr(done.content)
    assert done.model_id == "m1", repr(done.model_id)
    assert not done.degraded


def test_loop_race_fb_wins(llm_server: MockLLMServer) -> None:
    """竞速：本家过慢 → 备选胜，DONE 标记降级与实际模型。"""
    register(llm_server, "u2a", "m1", first_delay=1.0, chunks=["本家", "太慢"])
    register(llm_server, "u2b", "m2", first_delay=0.05, chunks=["备选", "先到"])
    engine = build_engine(
        llm_server,
        [
            {"id": "u2a", "models": [{"id": "m1"}]},
            {"id": "u2b", "models": [{"id": "m2"}]},
        ],
    )
    loop = make_loop(engine)
    evs = events_of(loop, user_messages("m1"), race_model="m2")
    done = [e for e in evs if e.type == LoopEventType.DONE][0]
    assert done.content == "备选先到", repr(done.content)
    assert done.model_id == "m2", repr(done.model_id)
    assert done.degraded
    assert done.race_possible


def test_loop_race_home_wins(llm_server: MockLLMServer) -> None:
    """竞速：微小差距内本家跟上 → 本家胜，不降级。"""
    register(llm_server, "u3a", "m1", first_delay=0.15, chunks=["本家", "回答"])
    register(llm_server, "u3b", "m2", first_delay=0.05, chunks=["备选", "更快"])
    engine = build_engine(
        llm_server,
        [
            {"id": "u3a", "models": [{"id": "m1"}]},
            {"id": "u3b", "models": [{"id": "m2"}]},
        ],
    )
    loop = make_loop(engine)
    evs = events_of(loop, user_messages("m1"), race_model="m2")
    done = [e for e in evs if e.type == LoopEventType.DONE][0]
    assert done.content == "本家回答", repr(done.content)
    assert done.model_id == "m1", repr(done.model_id)
    assert not done.degraded


def test_session_cycle(llm_server: MockLLMServer) -> None:
    """降级恢复循环：降级→记住模型→竞速回主模型→恢复后退出降级模式。"""
    register(llm_server, "u4a", "m1", errors=[500, 500])  # 主模型故障
    register(llm_server, "u4b", "m2", chunks=["降级回答"])
    engine = build_engine(
        llm_server,
        [
            {"id": "u4a", "models": [{"id": "m1", "fallback_models": ["m2"]}]},
            {"id": "u4b", "models": [{"id": "m2"}]},
        ],
    )
    s = ChatSession(engine, model_id="m1", tools_enabled=False)

    # 第 1 轮：主模型故障，模型级降级到 m2
    texts1 = list(s.ask("hi"))
    assert "".join(texts1) == "降级回答", repr("".join(texts1))
    assert s._degraded_model == "m2", repr(s._degraded_model)

    # 第 2 轮：主模型恢复 → 竞速应让本家胜（健康），退出降级模式
    register(llm_server, "u4a", "m1", first_delay=0.05, chunks=["主模型回复"])  # 覆盖为健康
    texts2 = list(s.ask("hi2"))
    assert "".join(texts2) == "主模型回复", repr("".join(texts2))
    assert s._degraded_model is None, repr(s._degraded_model)

    # 第 3 轮：主模型再度故障 → 再次降级并记住
    register(llm_server, "u4a", "m1", errors=[500, 500])
    texts3 = list(s.ask("hi3"))
    assert "".join(texts3) == "降级回答", repr("".join(texts3))
    assert s._degraded_model == "m2", repr(s._degraded_model)


def test_session_stall_cb(llm_server: MockLLMServer) -> None:
    """stall 回调可达；回答文本不受占位污染。"""
    register(llm_server, "u5a", "m1", first_delay=0.9)
    engine = build_engine(llm_server, [{"id": "u5a", "models": [{"id": "m1"}]}])
    s = ChatSession(engine, model_id="m1", tools_enabled=False)
    stalls: list[str] = []
    texts = list(s.ask("hi", on_stall=stalls.append))
    reply = "".join(texts)
    assert len(stalls) == 1, str(len(stalls))
    assert stalls and stalls[0] == ERROR_MSG, repr(stalls)
    assert ERROR_MSG not in reply, repr(reply)


def test_session_degraded_cb(llm_server: MockLLMServer) -> None:
    """降级回调携带实际生效模型 id；无降级时不回调。"""
    register(llm_server, "u6a", "m1", errors=[500, 500])
    register(llm_server, "u6b", "m2", chunks=["降级回答"])
    engine = build_engine(
        llm_server,
        [
            {"id": "u6a", "models": [{"id": "m1", "fallback_models": ["m2"]}]},
            {"id": "u6b", "models": [{"id": "m2"}]},
        ],
    )
    s = ChatSession(engine, model_id="m1", tools_enabled=False)
    degraded: list[str] = []
    list(s.ask("hi", on_degraded=degraded.append))
    assert degraded == ["m2"], repr(degraded)


def test_session_no_deg_no_cb(llm_server: MockLLMServer) -> None:
    """主模型健康时不触发降级回调。"""
    register(llm_server, "u7a", "m1", chunks=["正常回答"])
    engine = build_engine(llm_server, [{"id": "u7a", "models": [{"id": "m1"}]}])
    s = ChatSession(engine, model_id="m1", tools_enabled=False)
    degraded: list[str] = []
    texts = list(s.ask("hi", on_degraded=degraded.append))
    assert "".join(texts) == "正常回答", repr("".join(texts))
    assert degraded == [], repr(degraded)
    assert s._degraded_model is None
