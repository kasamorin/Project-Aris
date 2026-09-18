"""文本分块：标题层级切 + 定长兜底重叠（C2 定案，见 KNOWLEDGE-BASE.md 5.2）。

为什么这么切：

- 标题层级是作者给出的语义边界，切在中间会破坏上下文，也伤可引用性；
- 但单节可能很长，必须能硬切——否则一块超出 embedding 的可用上下文，检索粒度也太粗；
- 相邻块保留重叠，避免答案正好落在切口上被切散。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# markdown 标题（# ~ ######）与代码围栏（``` / ~~~）
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE = re.compile(r"^(```|~~~)")
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")


class ChunkingError(ValueError):
    """分块参数非法。"""


@dataclass(frozen=True)
class Chunk:
    """一个待入库的块。"""

    index: int
    heading_path: str
    content: str

    @property
    def char_count(self) -> int:
        """字符数（中文按字计，够用于粗粒度控制）。"""
        return len(self.content)

    @property
    def embed_text(self) -> str:
        """送 embedding 的文本：带标题路径前缀（短块靠它补上下文，提升召回）。"""
        return f"{self.heading_path}\n{self.content}" if self.heading_path else self.content


def _split_sections(text: str) -> list[tuple[str, str]]:
    """按标题切成 ``(heading_path, body)``；代码围栏内的 ``#`` 不算标题。"""
    sections: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []
    body: list[str] = []
    in_fence = False

    def flush() -> None:
        content = "\n".join(body).strip()
        if content:
            sections.append((" > ".join(title for _, title in stack), content))
        body.clear()

    for line in text.splitlines():
        if _FENCE.match(line.strip()):
            in_fence = not in_fence
            body.append(line)
            continue
        match = None if in_fence else _HEADING.match(line)
        if match:
            flush()
            level = len(match.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, match.group(2).strip()))
            continue
        body.append(line)
    flush()
    return sections


def _split_paragraphs(text: str) -> list[str]:
    """按空行切段落。"""
    return [p.strip() for p in _PARAGRAPH_SPLIT.split(text) if p.strip()]


def _hard_split(text: str, max_chars: int) -> list[str]:
    """把超长段落按句子边界硬切；单句仍超长则按长度切。"""
    pieces: list[str] = []
    buffer = ""
    for sentence in re.split(r"(?<=[。！？!?;；])\s*|\n", text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > max_chars:  # 单句就超长：先冲掉缓存，再按长度切
            if buffer:
                pieces.append(buffer)
                buffer = ""
            pieces.extend(sentence[i : i + max_chars] for i in range(0, len(sentence), max_chars))
            continue
        if buffer and len(buffer) + len(sentence) + 1 > max_chars:
            pieces.append(buffer)
            buffer = sentence
        else:
            buffer = f"{buffer} {sentence}".strip() if buffer else sentence
    if buffer:
        pieces.append(buffer)
    return [p for p in pieces if p]


def _overlap_tail(text: str, overlap_chars: int) -> str:
    """取上一块尾部作重叠，尽量从句子边界开始。"""
    if overlap_chars <= 0 or len(text) <= overlap_chars:
        return ""
    tail = text[-overlap_chars:]
    boundary = re.search(r"[。！？!?;；\n]", tail)
    return tail[boundary.end() :].strip() if boundary else tail.strip()


def _pack(
    paragraphs: list[str], *, max_chars: int, min_chars: int, overlap_chars: int
) -> list[str]:
    """把段落贪心打包成 ≤ max_chars 的窗口，相邻窗口带重叠。"""
    windows: list[str] = []
    current = ""
    for para in paragraphs:
        pieces = _hard_split(para, max_chars) if len(para) > max_chars else [para]
        for piece in pieces:
            if current and len(current) + len(piece) + 2 > max_chars:
                windows.append(current)
                prefix = _overlap_tail(current, overlap_chars)
                current = f"{prefix}\n{piece}".strip() if prefix else piece
            else:
                current = f"{current}\n\n{piece}".strip() if current else piece
    if current:
        windows.append(current)

    # 尾块过短则并入前一块（避免产生没有检索价值的碎片）
    if len(windows) >= 2 and len(windows[-1]) < min_chars:
        tail = windows.pop()
        windows[-1] = f"{windows[-1]}\n\n{tail}"
    return windows


def chunk_document(
    text: str,
    *,
    kind: str = "md",
    max_chars: int = 800,
    min_chars: int = 120,
    overlap_ratio: float = 0.15,
) -> list[Chunk]:
    """把文档切成块。

    ``kind="md"`` 走标题层级切分（HTML 也先转 markdown 再走这条），
    其余按段落定长打包。返回块按顺序编号。
    """
    if max_chars <= 0:
        raise ChunkingError("max_chars 必须为正整数")
    if not 0 <= overlap_ratio < 1:
        raise ChunkingError("overlap_ratio 必须落在 [0, 1)")
    if not text.strip():
        return []

    sections = _split_sections(text) if kind == "md" else [("", text)]
    overlap_chars = int(max_chars * overlap_ratio)

    chunks: list[Chunk] = []
    for heading_path, body in sections:
        for window in _pack(
            _split_paragraphs(body),
            max_chars=max_chars,
            min_chars=min_chars,
            overlap_chars=overlap_chars,
        ):
            chunks.append(Chunk(index=len(chunks), heading_path=heading_path, content=window))
    return chunks
