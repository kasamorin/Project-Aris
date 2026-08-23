"""技能管理路由——技能卡片列表、创建/编辑/删除 SKILL.md。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..templates import render

router = APIRouter()


@router.get("/skills", response_class=HTMLResponse)
async def skills_page(request: Request) -> HTMLResponse:
    """技能管理页面。"""
    skills = _load_skills()
    return render(request, "skills.html", {
        "active_page": "skills",
        "skills": skills,
    })


def _load_skills() -> list[dict]:
    """加载技能列表。"""
    from pathlib import Path
    skills_dir = Path("skills")
    if not skills_dir.exists():
        return []
    skills = []
    for d in sorted(skills_dir.iterdir()):
        if not d.is_dir():
            continue
        skill_md = d / "SKILL.md"
        description = ""
        if skill_md.exists():
            # 取第一行非空文本作为描述
            for line in skill_md.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    description = line[:100]
                    break
        skills.append({"name": d.name, "description": description})
    return skills
