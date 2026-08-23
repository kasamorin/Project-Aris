"""技能管理路由——技能卡片列表、创建/编辑/删除 SKILL.md。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..templates import render

router = APIRouter()

SKILLS_DIR = Path("skills")


@router.get("/skills", response_class=HTMLResponse)
async def skills_page(request: Request) -> HTMLResponse:
    """技能列表页面。"""
    skills = _load_skills()
    return render(request, "skills.html", {
        "active_page": "skills",
        "skills": skills,
    })


@router.get("/skills/{name}", response_class=HTMLResponse)
async def skill_detail(request: Request, name: str) -> HTMLResponse:
    """技能详情页面（SKILL.md 内容）。"""
    skill = _load_skill_detail(name)
    if skill is None:
        return render(request, "skills.html", {
            "active_page": "skills",
            "skills": _load_skills(),
            "error": f"技能 {name} 不存在",
        })
    return render(request, "skill_detail.html", {
        "active_page": "skills",
        "skill": skill,
    })


def _load_skills() -> list[dict]:
    """加载技能列表。"""
    if not SKILLS_DIR.exists():
        return []
    skills = []
    for d in sorted(SKILLS_DIR.iterdir()):
        if not d.is_dir():
            continue
        skill_md = d / "SKILL.md"
        description = ""
        if skill_md.exists():
            for line in skill_md.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    description = line[:100]
                    break
        skills.append({"name": d.name, "description": description})
    return skills


def _load_skill_detail(name: str) -> dict | None:
    """加载单个技能详情。"""
    skill_dir = SKILLS_DIR / name
    if not skill_dir.exists() or not skill_dir.is_dir():
        return None
    skill_md = skill_dir / "SKILL.md"
    content = ""
    if skill_md.exists():
        content = skill_md.read_text(encoding="utf-8")
    # 检查是否有 tools.py
    has_tools = (skill_dir / "tools.py").exists()
    return {
        "name": name,
        "content": content,
        "has_tools": has_tools,
    }
