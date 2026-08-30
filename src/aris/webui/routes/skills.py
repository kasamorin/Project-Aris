"""技能管理路由——技能卡片列表、创建/编辑/删除 SKILL.md。

技能目录的扫描/读写/路径安全校验均由总线服务 `skills.*` 负责
（注册在 behavior/skills/manager.py），路由只做薄展示与表单转发。
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from aris.core import call
from ..templates import render

router = APIRouter()


@router.get("/skills", response_class=HTMLResponse)
async def skills_page(request: Request) -> HTMLResponse:
    """技能列表页面。"""
    skills = call("skills.list") or []
    return render(request, "skills.html", {
        "active_page": "skills",
        "skills": skills,
    })


@router.get("/skills/{name}", response_class=HTMLResponse)
async def skill_detail(request: Request, name: str) -> HTMLResponse:
    """技能详情页面（SKILL.md 内容）。"""
    skill = call("skills.detail", name)
    if skill is None:
        return render(request, "skills.html", {
            "active_page": "skills",
            "skills": call("skills.list") or [],
            "error": f"技能 {name} 不存在",
        })
    return render(request, "skill_detail.html", {
        "active_page": "skills",
        "skill": skill,
    })


@router.post("/skills/create", response_model=None)
async def skill_create(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
) -> RedirectResponse:
    """创建新技能。"""
    ok, error = call("skills.create", name, description)
    if not ok:
        return RedirectResponse(url=f"/skills?error={quote(error)}", status_code=303)
    return RedirectResponse(url=f"/skills/{quote(name)}", status_code=303)


@router.get("/skills/{name}/edit", response_class=HTMLResponse)
async def skill_edit_page(request: Request, name: str) -> HTMLResponse:
    """技能编辑页面。"""
    skill = call("skills.detail", name)
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
    ok = call("skills.save", name, content)
    if not ok:
        return RedirectResponse(url="/skills", status_code=303)
    return RedirectResponse(url=f"/skills/{quote(name)}", status_code=303)


@router.post("/skills/{name}/delete", response_model=None)
async def skill_delete(name: str) -> RedirectResponse:
    """删除技能。"""
    call("skills.delete", name)
    return RedirectResponse(url="/skills", status_code=303)