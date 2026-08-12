"""SKILL.md 配置文件解析：提取 frontmatter 元数据（name / description）。

手写简易解析，只支持 frontmatter 顶层的两字段（本项目所需）：
```
---
name: note
description: 备忘能力，用于记录/查询简短笔记
---
```
解析失败时宽容降级（字段为空，不抛异常），与 cfgtoml 的容错风格一致。
若未来 frontmatter 字段变复杂（version、metadata 等），再引入 yaml 库。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SkillMeta:
    """skill 的元数据（来自 SKILL.md 的 frontmatter）。"""

    name: str = ""
    description: str = ""


def read_skill_meta(text: str) -> SkillMeta:
    """从 SKILL.md 文本中解析 frontmatter，返回元数据。

    不存在的字段留空字符串；无 frontmatter 或解析失败时全部为空。
    """
    meta = SkillMeta()
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return meta

    # frontmatter 结束于下一个单独的 --- 行
    lines = stripped.splitlines()[1:]
    for line in lines:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        # 简单处理单行引用/块引（description: | 多行暂不支持，留空）
        if not value or value.startswith(("|", ">")):
            value = ""
        else:
            value = value.strip('"').strip("'")
        if key == "name":
            meta.name = value
        elif key == "description":
            meta.description = value
    return meta