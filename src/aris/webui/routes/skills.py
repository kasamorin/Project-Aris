"""技能管理路由——技能卡片列表、创建/编辑/删除 SKILL.md。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

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
    has_tools = (skill_dir / "tools.py").exists()
    return {
        "name": name,
        "content": content,
        "has_tools": has_tools,
    }


@router.post("/skills/create", response_model=None)
async def skill_create(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
) -> RedirectResponse:
    """创建新技能。"""
    import re
    # 校验名称（仅允许英文、数字、连字符）
    if not re.match(r"^[a-z0-9-]+$", name):
        return RedirectResponse(url="/skills?error=名称格式错误", status_code=303)
    skill_dir = SKILLS_DIR / name
    if skill_dir.exists():
        return RedirectResponse(url=f"/skills?error={name} 已存在", status_code=303)
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    content = f"# {name}\n\n{description}\n" if description else f"# {name}\n"
    skill_md.write_text(content, encoding="utf-8")
    return RedirectResponse(url=f"/skills/{name}", status_code=303)


@router.get("/skills/{name}/edit", response_class=HTMLResponse)
async def skill_edit_page(request: Request, name: str) -> HTMLResponse:
    """技能编辑页面。"""
    skill = _load_skill_detail(name)
    if skill is None:
        return RedirectResponse(url="/skills", status_code=303)
    return render(request, "skill_edit.html", {
        "active_page": "skills",
        "skill": skill,
    })


@router.post("/skills/{name}/edit", response_model=None)
async def skill_edit_save(
    request: Request,
    name: str,
    content: str = Form(...),
) -> RedirectResponse:
    """保存技能编辑。"""
    skill_dir = SKILLS_DIR / name
    if not skill_dir.exists():
        return RedirectResponse(url="/skills", status_code=303)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(content, encoding="utf-8")
    return RedirectResponse(url=f"/skills/{name}", status_code=303)


@router.post("/skills/{name}/delete", response_model=None)
async def skill_delete(name: str) -> RedirectResponse:
    """删除技能。"""
    import shutil
    skill_dir = SKILLS_DIR / name
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    return RedirectResponse(url="/skills", status_code=303)
