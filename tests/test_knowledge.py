"""知识库测试：分块 / 载入（无外部依赖）与端到端摄入检索（需真库，未运行则跳过）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from aris.knowledge.chunking import ChunkingError, chunk_document
from aris.knowledge.loaders import LoadError, iter_files, load_document

# ---------------------------------------------------------------------------
# 分块：标题层级 + 定长兜底重叠
# ---------------------------------------------------------------------------

SAMPLE = """# 安装指南

先装依赖。

## 依赖

需要 Python 3.12 以上。

### 可选依赖

OpenVINO 用于本地推理。

# 使用

直接运行 aris chat。
"""


def test_chunks_follow_heading_hierarchy():
    chunks = chunk_document(SAMPLE, kind="md", max_chars=800)
    paths = [c.heading_path for c in chunks]

    assert paths == ["安装指南", "安装指南 > 依赖", "安装指南 > 依赖 > 可选依赖", "使用"]
    assert all(c.index == i for i, c in enumerate(chunks))
    assert "OpenVINO" in chunks[2].content


def test_embed_text_carries_heading_path():
    chunk = chunk_document(SAMPLE, kind="md")[2]
    assert chunk.embed_text.startswith("安装指南 > 依赖 > 可选依赖\n")


def test_code_fence_hash_is_not_a_heading():
    text = "# 标题\n\n```bash\n# 这是注释，不是标题\necho hi\n```\n"
    chunks = chunk_document(text, kind="md")

    assert len(chunks) == 1
    assert chunks[0].heading_path == "标题"
    assert "# 这是注释" in chunks[0].content


def test_long_section_is_split_with_overlap_and_respects_max():
    paragraph = "这是一句用于测试的句子，长度适中。" * 12  # 约 200 字
    text = "# 长文\n\n" + "\n\n".join([paragraph] * 6)
    chunks = chunk_document(text, kind="md", max_chars=300, min_chars=50, overlap_ratio=0.15)

    assert len(chunks) > 1
    assert all(c.char_count <= 300 + 60 for c in chunks)  # 允许重叠带来的少量超出
    # 相邻块应有重叠文字（前块尾部出现在后块开头）
    assert chunks[0].content[-20:].strip()[:10] in chunks[1].content


def test_plain_text_is_packed_by_paragraph():
    text = "\n\n".join(f"第 {i} 段内容。" for i in range(10))
    chunks = chunk_document(text, kind="plain", max_chars=40, min_chars=10)

    assert len(chunks) > 1
    assert all(c.heading_path == "" for c in chunks)


def test_empty_and_invalid_inputs():
    assert chunk_document("   \n\n  ") == []
    with pytest.raises(ChunkingError):
        chunk_document("x", max_chars=0)
    with pytest.raises(ChunkingError):
        chunk_document("x", overlap_ratio=1.0)


# ---------------------------------------------------------------------------
# 载入：格式过滤与标题提取
# ---------------------------------------------------------------------------


def test_load_markdown_extracts_title_and_hash(tmp_path):
    doc_file = tmp_path / "note.md"
    doc_file.write_text("# 我的笔记\n\n正文内容。", encoding="utf-8")

    doc = load_document(doc_file)

    assert doc.title == "我的笔记"
    assert doc.kind == "md"
    assert doc.byte_size > 0
    assert len(doc.content_hash) == 64


def test_load_html_converts_to_markdown(tmp_path):
    html = """<html><body><nav>导航条</nav><article><h1>网络文章</h1><p>第一段。</p>
    <h2>小节</h2><p>第二段。</p><ul><li>条目一</li></ul></article>
    <footer>页脚信息</footer></body></html>"""
    doc_file = tmp_path / "page.html"
    doc_file.write_text(html, encoding="utf-8")

    doc = load_document(doc_file)
    chunks = chunk_document(doc.text, kind=doc.kind)

    assert doc.kind == "md"
    assert doc.title == "网络文章"
    assert "第一段" in doc.text
    # 标题层级要保留（分块器靠它切节），导航/页脚等噪声要丢掉
    assert [c.heading_path for c in chunks] == ["网络文章", "网络文章 > 小节"]
    assert "导航条" not in doc.text
    assert "页脚信息" not in doc.text
    assert "- 条目一" in doc.text


def test_unsupported_suffix_is_rejected(tmp_path):
    pdf = tmp_path / "manual.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    with pytest.raises(LoadError):
        load_document(pdf)
    with pytest.raises(LoadError):
        iter_files([pdf])
    with pytest.raises(LoadError):
        iter_files([tmp_path / "not-exist.md"])


def test_iter_files_recurses_and_filters(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "sub" / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "sub" / "c.pdf").write_bytes(b"%PDF")
    (tmp_path / "sub" / "d.html").write_text("<p>d</p>", encoding="utf-8")

    found = [p.name for p in iter_files([tmp_path])]

    assert found == ["a.md", "b.txt", "d.html"]


# ---------------------------------------------------------------------------
# 端到端：摄入 → 检索 → 移除（需要真库与本地 embedding）
# ---------------------------------------------------------------------------


def _pg_available() -> bool:
    try:
        from aris.store import detect, is_running

        return is_running(detect())
    except Exception:
        return False


requires_pg = pytest.mark.skipif(not _pg_available(), reason="PostgreSQL 未运行（先 aris db start）")


@requires_pg
def test_ingest_search_remove_roundtrip(tmp_path: Path):
    """hash 幂等、变更重建、检索带来源、移除后查不到——一条链路全走通。"""
    from aris.knowledge import get_service

    service = get_service()
    service.ensure_schema()
    doc_path = tmp_path / "kb-roundtrip.md"
    original = "# 猫科动物\n\n橘猫喜欢晒太阳。\n\n## 饮食\n\n猫是肉食动物，需要牛磺酸。"
    doc_path.write_text(original, encoding="utf-8")

    try:
        first = service.ingest([str(doc_path)])
        assert first[0]["status"] == "added"
        assert first[0]["chunks"] >= 1

        again = service.ingest([str(doc_path)])
        assert again[0]["status"] == "skipped"

        doc_path.write_text(original + "\n\n还需要充足蛋白质。", encoding="utf-8")
        updated = service.ingest([str(doc_path)])
        assert updated[0]["status"] == "updated"

        hits = service.search("猫吃什么", limit=5)
        paths = [r["source_path"] for r in hits["results"]]
        # 库里可能有别的文档（如用户投喂的资料），故只断言本文档命中了
        assert str(doc_path.resolve()) in paths, hits["results"]
        mine = [r for r in hits["results"] if r["source_path"] == str(doc_path.resolve())]
        assert any(r["heading_path"] for r in mine)
        assert mine[0]["distance"] >= 0

        sources = service.list_sources()
        assert any(s["source_path"] == str(doc_path.resolve()) for s in sources)
    finally:
        service.remove(str(doc_path))

    assert not any(
        s["source_path"] == str(doc_path.resolve()) for s in service.list_sources()
    )
    hits = service.search("猫吃什么", limit=5)
    assert not any(r["source_path"] == str(doc_path.resolve()) for r in hits["results"])
