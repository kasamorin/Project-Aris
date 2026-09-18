"""knowledge_search 工具测试：返回格式（真库）+ agent loop 工具往返（脚本化 mock）。

`llm_server` 是本地回环的 OpenAI 兼容 mock（见 tests/support/mock_llm_server.py），
用「脚本序列」驱动：第 1 次请求回 tool_calls、第 2 次请求回最终回答——
零真实 API 消耗即可验证「模型决定查知识库 → 工具执行 → 结果回填 → 再作答」闭环。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aris.behavior import AgentLoop, LoopEventType
from aris.behavior.registry import ToolRegistry
from aris.behavior.tools import knowledge_search

from support.helpers import build_engine, events_of, user_messages
from support.mock_llm_server import MockLLMServer, Scenario, tool_call_chunk

DOC_TEXT = """# 部署手册

## 端口

Aris 的知识库数据库跑在 55432 端口，避免和系统 PostgreSQL 的 5432 冲突。

## 备份

数据目录是 data/pgdata，备份用 pg_dump。
"""


def _pg_available() -> bool:
    try:
        from aris.store import detect, is_running

        return is_running(detect())
    except Exception:
        return False


requires_pg = pytest.mark.skipif(
    not _pg_available(), reason="PostgreSQL 未运行（先 aris db start）"
)


@pytest.fixture
def registry() -> ToolRegistry:
    """只挂 knowledge_search 的工具注册表（避免真去联网）。"""
    reg = ToolRegistry()
    knowledge_search.register(reg)
    return reg


@pytest.fixture
def ingested_doc(tmp_path: Path):
    """摄入一份临时文档，用完移除（避免污染开发库）。"""
    from aris.knowledge import get_service

    service = get_service()
    service.ensure_schema()
    doc_path = tmp_path / "deploy.md"
    doc_path.write_text(DOC_TEXT, encoding="utf-8")
    service.ingest([str(doc_path)])
    try:
        yield doc_path
    finally:
        service.remove(str(doc_path))


@requires_pg
def test_tool_returns_sourced_markdown(registry: ToolRegistry, ingested_doc: Path) -> None:
    """工具返回外层 JSON + 内部 markdown，且每条带来源路径与标题层级。"""
    raw = registry.execute("knowledge_search", {"query": "知识库数据库端口是多少"})

    payload = json.loads(raw)
    assert payload["type"] == "knowledge_search_results"
    assert payload["count"] >= 1
    body = payload["results"]
    assert str(ingested_doc.resolve()) in body
    assert "› 部署手册 > 端口" in body
    assert "55432" in body


@requires_pg
def test_tool_respects_top_k(registry: ToolRegistry, ingested_doc: Path) -> None:
    raw = registry.execute("knowledge_search", {"query": "端口", "top_k": 1})
    payload = json.loads(raw)

    assert payload["count"] == 1
    assert payload["results"].count("\n   ") >= 1  # 至少一条内容块


@requires_pg
def test_tool_reports_distance_for_weak_hits(
    registry: ToolRegistry, ingested_doc: Path
) -> None:
    """不设相似度阈值（C4 定案）：无关查询也会返回最近片段，故必须给出距离供模型判断。"""
    unrelated = json.loads(
        registry.execute("knowledge_search", {"query": "量子纠缠退相干"})
    )

    assert unrelated["type"] == "knowledge_search_results"
    assert unrelated["count"] >= 1
    assert "距离" in unrelated["results"]


@requires_pg
def test_tool_reports_disabled(registry: ToolRegistry, ingested_doc: Path) -> None:
    """知识库关闭时明确说明，不抛异常。"""
    from aris.knowledge import get_service

    config = get_service().config
    config.enabled = False
    try:
        off = json.loads(registry.execute("knowledge_search", {"query": "端口"}))
    finally:
        config.enabled = True

    assert off["count"] == 0
    assert "已关闭" in off["results"]


def test_tool_handles_empty_results(monkeypatch) -> None:
    """库为空时的友好提示（直接替换总线调用，不需要数据库）。"""
    monkeypatch.setattr(
        knowledge_search,
        "call",
        lambda *a, **k: {"query": "", "results": [], "enabled": True},
    )
    reg = ToolRegistry()
    knowledge_search.register(reg)

    payload = json.loads(reg.execute("knowledge_search", {"query": "任意"}))

    assert payload["count"] == 0
    assert "没有找到" in payload["results"]


def test_tool_rejects_bad_arguments(registry: ToolRegistry) -> None:
    """参数不合法走错误返回（工具层宽容降级，不抛异常）。"""
    bad_query = json.loads(registry.execute("knowledge_search", {"query": "   "}))
    assert bad_query["type"] == "knowledge_search_error"

    bad_top_k = json.loads(
        registry.execute("knowledge_search", {"query": "端口", "top_k": 0})
    )
    assert bad_top_k["type"] == "knowledge_search_error"

    missing = registry.execute("knowledge_search", {})
    assert missing.startswith("[工具 knowledge_search 调用失败")  # registry 层兜底


@requires_pg
def test_agent_loop_calls_knowledge_search(
    llm_server: MockLLMServer, registry: ToolRegistry, ingested_doc: Path
) -> None:
    """脚本化 mock 两步：模型先要求查知识库，拿到结果后再作答。"""
    llm_server.register_script(
        [
            Scenario(
                tool_calls=[
                    tool_call_chunk(
                        0,
                        "call_kb",
                        "knowledge_search",
                        json.dumps({"query": "知识库数据库端口"}, ensure_ascii=False),
                    )
                ],
                finish_reason="tool_calls",
            ),
            Scenario(chunks=["知识库数据库跑在 55432 端口。"]),
        ],
        pid="kb1",
        model="m1",
    )
    engine = build_engine(llm_server, [{"id": "kb1", "models": [{"id": "m1"}]}])
    loop = AgentLoop(engine, registry=registry, model_id="m1", max_rounds=3)

    events = events_of(loop, user_messages("m1", "知识库数据库端口是多少？"))

    tools = [e for e in events if e.type == LoopEventType.TOOL]
    assert len(tools) == 1, repr(tools)
    assert tools[0].name == "knowledge_search"
    tool_payload = json.loads(tools[0].result)
    assert tool_payload["type"] == "knowledge_search_results"
    assert str(ingested_doc.resolve()) in tool_payload["results"]

    done = [e for e in events if e.type == LoopEventType.DONE][0]
    assert "55432" in done.content
    assert llm_server.request_count("kb1", "m1") == 2  # 工具轮 + 最终回答轮
