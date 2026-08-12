"""note 技能的实时工具实现。

笔记以纯文本文件存于 `<data_dir>/notes/`（data/ 不进 git）：
- note_save(title, content)：保存/覆盖一条笔记
- note_read(title)：读取一条笔记
- note_list()：列出全部笔记标题

标题做路径安全化（仅保留字母/数字/中文字符与常见符号），防目录穿越。
"""

from __future__ import annotations

import re
from pathlib import Path

from aris.config import get_settings
from aris.behavior.registry import ToolRegistry

# 标题路径安全化：去掉路径分隔符等危险字符
_SAFE_TITLE = re.compile(r"[^\w\-. ]", flags=re.UNICODE)


def _notes_dir() -> Path:
    """笔记目录（<data_dir>/notes），确保存在。"""
    notes_dir = get_settings().data_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    return notes_dir


def _note_path(title: str) -> Path:
    safe = _SAFE_TITLE.sub("", title.strip())
    if not safe:
        raise ValueError("标题不能为空")
    return _notes_dir() / f"{safe}.txt"


def _do_save(title: str, content: str) -> str:
    path = _note_path(title)
    path.write_text(content.strip(), encoding="utf-8")
    return f"已保存笔记「{title}」"


def _do_read(title: str) -> str:
    path = _note_path(title)
    if not path.exists():
        return f"没有找到笔记「{title}」（可用 note_list 查看全部）"
    return path.read_text(encoding="utf-8")


def _do_list() -> str:
    files = sorted(_notes_dir().glob("*.txt"))
    if not files:
        return "还没有任何笔记。"
    lines = [f"- {f.stem}" for f in files]
    return "\n".join(lines)


def register(registry: ToolRegistry) -> None:
    """向 registry 注册 note 技能的工具。"""

    def _save(title: str, content: str) -> str:
        return _do_save(title, content)

    def _read(title: str) -> str:
        return _do_read(title)

    def _list() -> str:
        return _do_list()

    registry.register(
        "note_save",
        description=(
            "保存/更新一条笔记（标题唯一，重复保存覆盖原文）。"
            "标题要简短，内容写完整。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "笔记标题，简短"},
                "content": {"type": "string", "description": "笔记内容"},
            },
            "required": ["title", "content"],
            "additionalProperties": False,
        },
        fn=_save,
    )
    registry.register(
        "note_read",
        description="读取一条笔记的内容。",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "笔记标题"},
            },
            "required": ["title"],
            "additionalProperties": False,
        },
        fn=_read,
    )
    registry.register(
        "note_list",
        description="列出所有已保存的笔记标题。",
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        fn=_list,
    )