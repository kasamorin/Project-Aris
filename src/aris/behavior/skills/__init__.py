"""技能（Skill）系统。详见 `developDoc/SKILLS.md`。

skill 是目录化能力包：`skills/<name>/SKILL.md`（frontmatter 元数据 + 使用
手册）+ 可选 `tools.py`（注册工具）。三层渐进式披露：

1. 菜单：只读 frontmatter（name/description）注入 system prompt。
2. 激活：模型调用 `activate_skill(name)`，读取 SKILL.md 全文 + 装载工具。
3. 详情：references/ 等按需读取（预留，后续 skill 实现时再启用）。
"""

from .manager import Skill, SkillManager

__all__ = ["Skill", "SkillManager"]