"""内置工具：knowledge_search —— 检索用户投喂的本地知识库（RAG）。

与 `web_search` 并列的检索工具（D1 定案）：**由 Aris 自主判断何时查**，
不做每轮自动 RAG 注入。返回格式沿用 web_search 约定（D3）：外层 JSON 标识类型，
内部 markdown 省 token，**每条必带来源标识**（文件路径 + 标题 + 标题层级）——
可引用是知识库的存在意义。

本文件只是薄壳：知识库能力由 `knowledge/` 提供、经总线 `knowledge.search` 暴露，
工具不直接 import 业务实现（AGENTS.md「模块间调用规则」）。
"""

from __future__ import annotations

import json

from loguru import logger

from aris.core import call
from ..registry import ToolRegistry

# 单块内容截断上限：与分块上限（config/knowledge.toml: max_chars）同量级，
# 防止一次检索把上下文吃光
MAX_CONTENT_CHARS = 800

RESULT_TYPE = "knowledge_search_results"
ERROR_TYPE = "knowledge_search_error"


def _label(hit: dict) -> str:
    """结果标题行：标题（与文件名不同才显示）｜路径 › 标题层级（距离）。

    距离一并给出是有意的：C4 定案「初期不设相似度阈值」，纯向量检索必然返回
    最近的若干片段（无关查询也有结果），模型需要距离来判断值不值得用。
    """
    path = str(hit.get("source_path", ""))
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    title = str(hit.get("title") or "").strip()
    prefix = f"{title}｜" if title and title != stem else ""
    heading = f" › {hit['heading_path']}" if hit.get("heading_path") else ""
    distance = hit.get("distance")
    suffix = f"（距离 {float(distance):.3f}）" if distance is not None else ""
    return f"{prefix}{path}{heading}{suffix}"


def _format_markdown(results: list[dict]) -> str:
    """把命中片段拼成省 token 的 markdown（每条带自增 id 与来源）。"""
    blocks: list[str] = []
    for hit in results:
        content = str(hit.get("content", ""))[:MAX_CONTENT_CHARS]
        indented = "\n".join(f"   {line}" for line in content.splitlines())
        blocks.append(f"{hit.get('id')}. {_label(hit)}\n{indented}")
    return "\n".join(blocks)


def _error(message: str, query: str = "") -> str:
    """统一的失败返回（宽容降级：交给模型消化，不抛到 UI）。"""
    return json.dumps(
        {"type": ERROR_TYPE, "query": query, "error": message}, ensure_ascii=False
    )


def _do_search(query: str, top_k: int | None = None) -> str:
    """执行检索并组装工具返回值（JSON 字符串）。"""
    # 确保 knowledge 模块已导入（各模块 import 时自注册总线服务）
    import aris.knowledge  # noqa: F401

    if not isinstance(query, str) or not query.strip():
        return _error("query 不能为空")
    if top_k is not None and (not isinstance(top_k, int) or top_k <= 0):
        return _error(f"top_k 必须是正整数，收到 {top_k!r}", query)

    try:
        payload = call("knowledge.search", query, limit=top_k)
    except Exception as exc:  # noqa: BLE001 —— 工具层宽容降级
        logger.warning(f"知识库检索失败：{exc}")
        return _error(str(exc), query)

    results = list(payload.get("results", []))
    if not payload.get("enabled", True):
        body = "（知识库当前已关闭：config/knowledge.toml 的 enabled = false）"
    elif not results:
        body = "（知识库中没有找到相关内容）"
    else:
        body = _format_markdown(results)

    return json.dumps(
        {
            "type": RESULT_TYPE,
            "query": query,
            "count": len(results),
            "results": body,
        },
        ensure_ascii=False,
    )


def register(registry: ToolRegistry) -> None:
    """向 registry 注册 knowledge_search 工具。"""

    def _fn(query: str, top_k: int | None = None) -> str:
        return _do_search(query, top_k)

    registry.register(
        "knowledge_search",
        description=(
            "检索用户投喂的本地知识库（md / txt / html 资料）。"
            "当问题可能涉及用户提供的文档、笔记或资料时使用；"
            "参数 query 用自然语言即可。返回带来源路径与标题层级的片段，"
            "引用时请标注来源。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "检索词，自然语言即可",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回条数（默认取配置 top_k）",
                    "minimum": 1,
                    "maximum": 20,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        fn=_fn,
    )
