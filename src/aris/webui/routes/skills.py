"""技能管理路由——技能卡片列表、创建/编辑/删除 SKILL.md。

安全约定：所有 {name} 路径参数必须通过 _validate_skill_name 校验
（小写字母/数字/连字符），杜绝路径穿越；删除/写入前再用 resolve()
二次确认目标仍在 skills 目录内。
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..templates import render

# 与运行时 SkillManager 同源：包内 behavior/skills/ 目录，
# 保证 WebUI 管理的就是实际加载的技能（不再依赖进程 CWD）
from ...behavior.skills.manager import SKILLS_DIR as _PKG_SKILLS_DIR

router = APIRouter()

# 技能目录：优先用环境变量覆盖的场景不存在，直接与运行时同源
SKILLS_DIR: Path = _PKG_SKILLS_DIR

# 合法技能名：小写字母、数字、连字符（与 SkillManager frontmatter 约定一致）
_NAME_RE = re.compile(r"[a-z0-9-]+")


def _validate_skill_name(name: str) -> bool:
    """校验技能名是否合法（fullmatch 防尾部换行绕过）。"""
    return bool(_NAME_RE.fullmatch(name))


def _safe_skill_dir(name: str) -> Path | None:
    """返回校验通过的技能目录；名字非法或解析后越界则返回 None。"""
    if not _validate_skill_name(name):
        return None
    skill_dir = (SKILLS_DIR / name).resolve()
    # 双保险：resolve 后必须仍在 skills 目录内
    if not skill_dir.is_relative_to(SKILLS_DIR.resolve()):
        return None
    return skill_dir


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
    skill_dir = _safe_skill_dir(name)
    skill = _load_skill_detail(skill_dir) if skill_dir else None
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


def _load_skill_detail(skill_dir: Path) -> dict | None:
    """加载单个技能详情（入参为已校验的目录路径）。"""
    if not skill_dir.exists() or not skill_dir.is_dir():
        return None
    skill_md = skill_dir / "SKILL.md"
    content = ""
    if skill_md.exists():
        content = skill_md.read_text(encoding="utf-8")
    has_tools = (skill_dir / "tools.py").exists()
    return {
        "name": skill_dir.name,
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
    if not _validate_skill_name(name):
        return RedirectResponse(url="/skills?error=%E5%90%8D%E7%A7%B0%E6%A0%BC%E5%BC%8F%E9%94%99%E8%AF%AF", status_code=303)
    skill_dir = SKILLS_DIR / name
    if skill_dir.exists():
        return RedirectResponse(
            url=f"/skills?error={quote(name)}%20%E5%B7%B2%E5%AD%98%E5%9C%A8", status_code=303
        )
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    content = f"# {name}\n\n{description}\n" if description else f"# {name}\n"
    skill_md.write_text(content, encoding="utf-8")
    return RedirectResponse(url=f"/skills/{name}", status_code=303)


@router.get("/skills/{name}/edit", response_class=HTMLResponse)
async def skill_edit_page(request: Request, name: str) -> HTMLResponse:
    """技能编辑页面。"""
    skill_dir = _safe_skill_dir(name)
    skill = _load_skill_detail(skill_dir) if skill_dir else None
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
    skill_dir = _safe_skill_dir(name)
    if skill_dir is None or not skill_dir.exists():
        return RedirectResponse(url="/skills", status_code=303)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(content, encoding="utf-8")
    return RedirectResponse(url=f"/skills/{name}", status_code=303)


@router.post("/skills/{name}/delete", response_model=None)
async def skill_delete(name: str) -> RedirectResponse:
    """删除技能。"""
    skill_dir = _safe_skill_dir(name)
    # 额外防线：必须是技能目录本体（拒绝根目录/skills 本身被删）
    if (
        skill_dir is not None
        and skill_dir != SKILLS_DIR.resolve()
        and skill_dir.is_dir()
    ):
        shutil.rmtree(skill_dir)
    return RedirectResponse(url="/skills", status_code=303)
