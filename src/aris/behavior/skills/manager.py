"""技能（Skill）管理器：发现 / 菜单 / 激活 / 注册。

skill 是目录化能力包（SKILL.md + 可选 tools.py），遵循三层渐进式披露：
- 菜单（L1）：启动时只读各 skill 的 frontmatter（name/description），
  注入 system prompt 供模型判断何时激活（省 token）。
- 激活（L2）：模型调用 `activate_skill(name)` → 读取该 SKILL.md 全文、
  加载其 tools.py 的工具注册进 registry、返回正文给模型。
- 详情（L3）：references/ 等按需读取（预留，AstrBook skill 时再实现）。

激活是幂等的：已激活的 skill 重复激活只返回正文，不重复注册工具。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from ..registry import ToolRegistry
from .frontmatter import SkillMeta, read_skill_meta

# skills 目录（相对本文件，包内），每个子目录是一个 skill
SKILLS_DIR = Path(__file__).resolve().parent
# 激活返回的 SKILL.md 正文最大长度（字符，超过提示截断，遵循『正文要短』约定）
_DESC_MAX = 200


@dataclass
class Skill:
    """一个已发现的 skill：目录、元数据、路径。"""

    name: str
    meta: SkillMeta
    path: Path


class SkillManager:
    """扫描 skills/ 目录，提供技能菜单与按需激活。

    在 session 构造时实例化（装配动作），并把 `activate_skill` 注册进
    registry 供模型调用；菜单文本经 `core.call("skills.menu")` 获取。
    """

    def __init__(self, registry: ToolRegistry, skills_dir: Path | None = None) -> None:
        self.registry = registry
        self.skills_dir = skills_dir or SKILLS_DIR
        self._skills: dict[str, Skill] = {}
        self._activated: set[str] = set()
        from aris.core import provide

        provide("skills.menu", self.menu)
        self._discover()
        registry.register(
            "activate_skill",
            description=(
                "激活一个可用技能（skill），读取其使用手册并把相关工具装载给当前会话。"
                "参数 name 必须是系统提示中列出的技能名。"
                "当需要用到某个技能描述的能力时调用它。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "要激活的技能名（见系统的可用技能列表）",
                    },
                },
                "required": ["name"],
                "additionalProperties": False,
            },
            fn=self.activate,
        )

    def _discover(self) -> None:
        """扫描 skills 目录，收集各 skill 的元数据（只读 frontmatter）。"""
        for child in self.skills_dir.iterdir():
            skill_md = child / "SKILL.md"
            if not child.is_dir() or not skill_md.exists():
                continue
            try:
                text = skill_md.read_text(encoding="utf-8")
            except OSError as e:
                logger.warning(f"skill {child.name} 的 SKILL.md 读取失败: {e}")
                continue
            meta = read_skill_meta(text)
            if not meta.name:
                logger.warning(f"skill {child.name} 缺少 name，忽略")
                continue
            self._skills[meta.name] = Skill(name=meta.name, meta=meta, path=child)

    def menu(self) -> str:
        """技能菜单文本：各 skill 的 name + 精简描述，供注入 system prompt。"""
        if not self._skills:
            return ""
        lines = ["可用技能（skill）列表："]
        for name, skill in self._skills.items():
            desc = skill.meta.description.strip()
            if len(desc) > _DESC_MAX:
                desc = desc[:_DESC_MAX] + "…"
            lines.append(f"- {name}：{desc}")
        lines.append("需要用某技能时调用 activate_skill 激活。")
        return "\n".join(lines)

    def _load_tools(self, skill: Skill) -> None:
        """加载 skill 的 tools.py（若有），把工具注册进 registry。"""
        tools_py = skill.path / "tools.py"
        if not tools_py.exists():
            return
        spec = importlib.util.spec_from_file_location(
            f"aris.behavior.skills.{skill.name}.tools", tools_py
        )
        if spec is None or spec.loader is None:
            logger.warning(f"skill {skill.name} 的 tools.py 无法加载")
            return
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
            register = getattr(module, "register", None)
            if callable(register):
                register(self.registry)
            else:
                logger.warning(f"skill {skill.name} 的 tools.py 缺少 register(registry) 函数")
        except Exception as e:  # noqa: BLE001 —— skill 工具加载失败不影响主流程
            logger.warning(f"skill {skill.name} 的工具加载失败: {e}")

    def activate(self, name: str) -> str:
        """激活 skill：读取 SKILL.md 全文并装载工具，返回正文 JSON。

        幂等：重复激活仅返回正文。skill 不存在时返回可读错误
        （宽容降级，模型可自行判断）。
        """
        skill = self._skills.get(name)
        if skill is None:
            known = ", ".join(self._skills) if self._skills else "（无）"
            return json.dumps(
                {
                    "type": "skill_activate_error",
                    "name": name,
                    "error": f"技能 {name} 不存在，可用技能：{known}。需先列出或检查名字。",
                },
                ensure_ascii=False,
            )
        if name not in self._activated:
            self._load_tools(skill)
            self._activated.add(name)
        try:
            content = (skill.path / "SKILL.md").read_text(encoding="utf-8")
        except OSError as e:
            return json.dumps(
                {"type": "skill_activate_error", "name": name, "error": f"读取失败：{e}"},
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "type": "skill_activated",
                "name": name,
                "description": skill.meta.description,
                "manual": content,
                "note": "该技能的工具已装载，现在可直接使用。",
            },
            ensure_ascii=False,
        )