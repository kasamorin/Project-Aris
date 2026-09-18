"""WebUI 知识库页面测试：文件名安全、上传限额（无库）+ 上传→列表→检索→移除（真库）。

真库用例在 PostgreSQL 未运行时自动跳过（先 `aris db start`）。上传走后台任务，
TestClient 会等 BackgroundTasks 跑完，故响应结束后即可轮询到终态。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aris.knowledge.service import KnowledgeError, safe_filename

# ---------------------------------------------------------------------------
# 文件名安全（无外部依赖）
# ---------------------------------------------------------------------------


def test_safe_filename_strips_paths_and_control_chars() -> None:
    assert safe_filename("note.md") == "note.md"
    assert safe_filename("../../etc/passwd") == "passwd"  # 只取 basename
    assert safe_filename("/abs/path/手册.md") == "手册.md"
    assert safe_filename("a\\b\\c.md") == "a_b_c.md"  # 反斜杠不是路径分隔符，替换掉
    assert safe_filename("bad\x00name.md") == "bad_name.md"


def test_safe_filename_rejects_empty_and_overlong() -> None:
    for bad in ("", "   ", ".", "..", "/"):
        with pytest.raises(KnowledgeError):
            safe_filename(bad)
    with pytest.raises(KnowledgeError):
        safe_filename("x" * 300 + ".md")


# ---------------------------------------------------------------------------
# 上传限额（坏文件在摄入之前就被挡掉，不需要数据库）
# ---------------------------------------------------------------------------


def _service(tmp_path: Path):
    from aris.knowledge import get_service

    return get_service()


@pytest.fixture
def upload_service(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """把 data_dir 指到 tmp，上传落到 tmp/data/knowledge（不污染真实仓库）。"""
    from aris.config import get_settings

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path / "data")
    return _service(tmp_path)


def test_upload_rejects_bad_items_before_ingest(upload_service, tmp_path: Path) -> None:
    config = upload_service.config
    outcomes = upload_service.upload(
        [
            {"filename": "big.md", "data": b"x" * (config.max_file_bytes + 1)},
            {"filename": "note.pdf", "data": b"%PDF-1.4"},
            {"filename": "empty.md", "data": b""},
        ]
    )

    assert [o["status"] for o in outcomes] == ["failed", "failed", "failed"]
    assert "上限" in outcomes[0]["reason"]
    assert "不支持的格式" in outcomes[1]["reason"]
    assert "为空" in outcomes[2]["reason"]
    # 全被拒 → 目录会被预先建好（提前暴露权限问题），但不落任何文件、不触发摄入
    upload_dir = tmp_path / "data" / "knowledge"
    assert upload_dir.exists()
    assert list(upload_dir.iterdir()) == []


def test_upload_enforces_count_limit(upload_service) -> None:
    limit = upload_service.config.max_files_per_upload
    items = [{"filename": f"n{i}.md", "data": b"x"} for i in range(limit + 1)]

    with pytest.raises(KnowledgeError):
        upload_service.upload(items)


def test_upload_refuses_when_disabled(upload_service) -> None:
    config = upload_service.config
    config.enabled = False
    try:
        with pytest.raises(KnowledgeError):
            upload_service.upload([{"filename": "n.md", "data": b"x"}])
    finally:
        config.enabled = True


# ---------------------------------------------------------------------------
# WebUI 路由 + 端到端（上传 → 列表 → 检索 → 移除；agent 回答用脚本化 mock）
# ---------------------------------------------------------------------------


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
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """带登录、data_dir 隔离的 WebUI 测试客户端。"""
    monkeypatch.setenv("ARIS_WEBUI_PASSWORD", "test-pass")

    from aris.webui import rate_limit

    monkeypatch.setattr(rate_limit.login_limiter, "_attempts", {})

    from aris.config import get_settings

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path / "data")
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    from fastapi.testclient import TestClient

    from aris.webui import create_app

    with TestClient(create_app(), follow_redirects=False) as c:
        c.post("/login", data={"password": "test-pass"})
        yield c


@requires_pg
def test_webui_knowledge_page_renders(client) -> None:
    r = client.get("/knowledge")

    assert r.status_code == 200
    assert "知识库" in r.text
    assert "上传资料" in r.text
    assert "检索试验" in r.text


@requires_pg
def test_webui_upload_ingest_search_remove(client, monkeypatch) -> None:
    """上传 → 后台摄入 → 轮询到完成 → 列表出现 → 检索命中 → 移除后消失。"""
    content = (
        "# 家庭网络\n\n## NAS\n\nNAS 的 IP 是 192.168.1.20，管理端口 5000。\n\n"
        "## 路由\n\n主路由在客厅。\n"
    ).encode("utf-8")
    r = client.post(
        "/knowledge/upload",
        files=[("files", ("kb-webui.md", content, "text/markdown"))],
    )
    assert r.status_code == 303
    job_url = r.headers["location"]
    assert job_url.startswith("/knowledge?job=")
    job_id = job_url.split("job=", 1)[1]

    job = client.get(f"/knowledge/jobs/{job_id}").json()
    assert job["status"] == "done", job
    assert job["items"][0]["status"] == "added"
    assert job["items"][0]["chunks"] >= 1

    page = client.get("/knowledge")
    assert "kb-webui.md" in page.text

    hit = client.get("/knowledge", params={"q": "NAS 的 IP 是多少"})
    assert "192.168.1.20" in hit.text
    assert "距离" in hit.text

    # 落盘位置在 data/knowledge 下（source_path 可引用）
    from aris.config import get_settings

    saved = Path(get_settings().data_dir) / "knowledge" / "kb-webui.md"
    assert saved.exists()

    client.post("/knowledge/remove", data={"path": str(saved.resolve())})
    after = client.get("/knowledge")
    assert "kb-webui.md" not in after.text


@requires_pg
def test_uploaded_doc_is_retrievable_by_agent(client, llm_server, monkeypatch) -> None:
    """全链路：WebUI 上传 → 知识库 → Aris 自主调用 knowledge_search 作答。"""
    content = "# 值班表\n\n周三的值班人是 Morin，联系方式 13800000000。\n".encode("utf-8")
    r = client.post(
        "/knowledge/upload", files=[("files", ("duty.md", content, "text/markdown"))]
    )
    job_id = r.headers["location"].split("job=", 1)[1]
    assert client.get(f"/knowledge/jobs/{job_id}").json()["status"] == "done"

    from aris.behavior import AgentLoop, LoopEventType
    from aris.behavior.registry import ToolRegistry
    from aris.behavior.tools import knowledge_search
    from aris.config import get_settings
    from support.helpers import build_engine, events_of, user_messages
    from support.mock_llm_server import Scenario, tool_call_chunk

    llm_server.register_script(
        [
            Scenario(
                tool_calls=[
                    tool_call_chunk(
                        0, "c1", "knowledge_search", json.dumps({"query": "周三谁值班"})
                    )
                ],
                finish_reason="tool_calls",
            ),
            Scenario(chunks=["周三值班的是 Morin。"]),
        ],
        pid="kbw", model="m1",
    )
    engine = build_engine(llm_server, [{"id": "kbw", "models": [{"id": "m1"}]}])
    registry = ToolRegistry()
    knowledge_search.register(registry)
    loop = AgentLoop(engine, registry=registry, model_id="m1", max_rounds=3)

    events = events_of(loop, user_messages("m1", "周三谁值班？"))

    tool_events = [e for e in events if e.type == LoopEventType.TOOL]
    assert tool_events and "13800000000" in tool_events[0].result
    done = [e for e in events if e.type == LoopEventType.DONE][0]
    assert "Morin" in done.content

    saved = Path(get_settings().data_dir) / "knowledge" / "duty.md"
    client.post("/knowledge/remove", data={"path": str(saved.resolve())})
