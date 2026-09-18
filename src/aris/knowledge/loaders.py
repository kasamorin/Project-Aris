"""文件读取：md / txt / html → 纯文本 + 元数据。

HTML 用既有的 BeautifulSoup 自行转 markdown——**不用 trafilatura 的 markdown 输出**：
实测它会把标题层级抹平（整篇并成一个 ``<p>``），而标题层级正是分块器要用的语义
边界（C2 定案）。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

# 首期支持范围（B2 定案：md / txt / html；PDF 留第二阶段）
SUPPORTED_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".html", ".htm"})
MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})
HTML_SUFFIXES = frozenset({".html", ".htm"})

# HTML 转 markdown 时丢弃的噪声标签，以及要映射成 markdown 的块级标签
_HTML_DROP_TAGS = (
    "script",
    "style",
    "noscript",
    "template",
    "nav",
    "footer",
    "header",
    "form",
    "aside",
    "iframe",
    "svg",
)
_HTML_BLOCK_TAGS = frozenset({"p", "li", "blockquote", "figcaption", "td", "th"})


class LoadError(RuntimeError):
    """文件读取/解析失败（格式不支持、正文抽不到、路径不存在）。"""


@dataclass(frozen=True)
class LoadedDoc:
    """一个待摄入的文档。"""

    path: Path
    title: str
    text: str
    kind: str  # "md"（有标题语义）/ "plain"
    content_hash: str
    byte_size: int
    mtime: datetime


def iter_files(targets: list[Path]) -> list[Path]:
    """把文件/目录展开成待摄入文件列表（目录递归、过滤后缀、顺序稳定、去重）。"""
    found: list[Path] = []
    for target in targets:
        path = target.expanduser()
        if path.is_dir():
            found.extend(
                p
                for p in sorted(path.rglob("*"))
                if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
            )
        elif path.is_file():
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                supported = "，".join(sorted(SUPPORTED_SUFFIXES))
                raise LoadError(f"不支持的格式：{path.name}（支持 {supported}）")
            found.append(path)
        else:
            raise LoadError(f"路径不存在：{path}")

    unique = {str(p.resolve()): p for p in found}
    return [unique[key] for key in sorted(unique)]


def _extract_title(text: str, fallback: str) -> str:
    """取首个 markdown 一级标题，没有就用文件名。"""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
        if stripped:
            break
    return fallback


def _html_to_markdown(raw: str, path: Path) -> str:
    """HTML → 带标题层级的 markdown（先丢噪声，再映射块级元素）。"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(list(_HTML_DROP_TAGS)):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup

    lines: list[str] = []
    _collect_blocks(root, lines)
    if not lines:
        raise LoadError(f"未能从 HTML 抽取正文：{path.name}")
    return "\n\n".join(lines)


def _collect_blocks(node: object, lines: list[str]) -> None:
    """递归收集块级元素；命中即不再下钻，避免父子内容重复输出。"""
    for child in getattr(node, "children", []):
        name = getattr(child, "name", None)
        if name is None:  # 纯文本节点由所属块级元素统一取
            continue
        if re.fullmatch(r"h[1-6]", name):
            text = child.get_text(" ", strip=True)
            if text:
                lines.append(f"{'#' * int(name[1])} {text}")
        elif name == "pre":
            text = child.get_text("\n", strip=True)
            if text:
                lines.append(f"```\n{text}\n```")
        elif name in _HTML_BLOCK_TAGS:
            text = child.get_text(" ", strip=True)
            if not text:
                continue
            prefix = "- " if name == "li" else ("> " if name == "blockquote" else "")
            lines.append(prefix + text)
        else:
            _collect_blocks(child, lines)


def load_document(path: Path) -> LoadedDoc:
    """读取并解析一个文件。"""
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise LoadError(f"不支持的格式：{path.name}")
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise LoadError(f"读取失败：{path}（{exc}）") from exc

    raw = raw_bytes.decode("utf-8", errors="replace")
    if suffix in HTML_SUFFIXES:
        text, kind = _html_to_markdown(raw, path), "md"
    elif suffix in MARKDOWN_SUFFIXES:
        text, kind = raw, "md"
    else:
        text, kind = raw, "plain"

    if not text.strip():
        raise LoadError(f"文件没有可用正文：{path.name}")
    logger.debug(f"载入 {path}（{kind}，{len(text)} 字符）")
    return LoadedDoc(
        path=path,
        title=_extract_title(text, path.stem),
        text=text,
        kind=kind,
        content_hash=hashlib.sha256(raw_bytes).hexdigest(),
        byte_size=len(raw_bytes),
        mtime=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
    )
