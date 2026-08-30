"""配置管理路由——查看/编辑 config/*.toml，.env 状态只读。"""

from __future__ import annotations

import os
import shutil
import datetime
from pathlib import Path

import tomllib
from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..templates import render

router = APIRouter()

# 模块配置映射：name → (label, toml_file, dataclass_fields)
# dataclass_fields 由各模块的 config dataclass 定义，这里用简单映射
_MODULES = {
    "chat": "对话",
    "search": "搜索",
    "audit": "审计",
    "logging": "日志",
    "notify": "通知",
    "webui": "WebUI",
}

# 每个模块的可调参数描述
_MODULE_FIELDS: dict[str, list[dict]] = {
    "chat": [
        {"key": "temperature", "description": "采样温度，0=确定性，1=随机性较高"},
        {"key": "top_p", "description": "核采样概率质量"},
        {"key": "max_rounds", "description": "agent loop 最多执行轮数"},
        {"key": "log_rotation_bytes", "description": "对话日志轮转阈值（字节）"},
        {"key": "tool_result_preview_len", "description": "工具结果预览截断长度"},
    ],
    "search": [
        {"key": "prefer_engine", "description": "首选搜索引擎（bing/tavily/auto）"},
        {"key": "timeout_seconds", "description": "HTTP 请求超时（秒）"},
        {"key": "results_count", "description": "返回搜索结果条数"},
        {"key": "snippet_max_len", "description": "摘要截断长度（字符）"},
        {"key": "webopen_timeout_seconds", "description": "web_open 超时（秒）"},
        {"key": "webopen_max_chars", "description": "web_open 返回正文最大长度"},
    ],
    "audit": [
        {"key": "max_records", "description": "环形缓冲上限"},
        {"key": "recent_default_limit", "description": "query_recent 默认返回条数"},
    ],
    "logging": [
        {"key": "file_rotation", "description": "单个日志文件大小上限"},
        {"key": "retention", "description": "日志保留期"},
    ],
    "notify": [
        {"key": "timeout_seconds", "description": "弹窗子进程超时（秒）"},
    ],
    "webui": [
        {"key": "host", "description": "监听地址"},
        {"key": "port", "description": "监听端口"},
        {"key": "session_days", "description": "会话有效天数"},
    ],
}


@router.get("/config", response_class=HTMLResponse)
async def config_page(
    request: Request,
    module: str | None = Query(None),
) -> HTMLResponse:
    """配置管理页面。"""
    env_vars = _check_env_vars()
    modules = [{"name": k, "label": v} for k, v in _MODULES.items()]
    fields = []
    current_module_label = ""
    if module and module in _MODULE_FIELDS:
        fields = _load_module_fields(module)
        current_module_label = _MODULES.get(module, module)
    return render(request, "config.html", {
        "active_page": "config",
        "env_vars": env_vars,
        "modules": modules,
        "current_module": module,
        "current_module_label": current_module_label,
        "fields": fields,
    })


@router.post("/config/save", response_model=None)
async def config_save(
    request: Request,
    module: str = Form(...),
) -> RedirectResponse:
    """保存模块配置。module 必须在白名单内（防路径穿越写任意 toml）。"""
    if module not in _MODULES:
        return RedirectResponse(url="/config", status_code=303)
    # 备份旧配置
    _backup_config(module)
    # 读取表单数据并写回 toml
    form_data = await request.form()
    _save_module_config(module, dict(form_data))
    return RedirectResponse(url=f"/config?module={module}", status_code=303)


def _check_env_vars() -> list[dict]:
    """检查 ARIS_* 环境变量是否已配置。"""
    vars_to_check = [
        "ARIS_WEBUI_PASSWORD",
        "ARIS_DATA_DIR",
        "ARIS_LLM_PROVIDERS_FILE",
        "TAVILY_API_KEY",
        "OPENCODE_API_KEY",
    ]
    return [
        {"name": v, "configured": bool(os.environ.get(v))}
        for v in vars_to_check
    ]


def _load_module_fields(module: str) -> list[dict]:
    """从 toml 文件加载模块配置字段。"""
    from ...cfgtoml import config_dir
    toml_path = config_dir() / f"{module}.toml"
    values = {}
    if toml_path.exists():
        with open(toml_path, "rb") as f:
            values = tomllib.load(f)
    fields = []
    for field_def in _MODULE_FIELDS.get(module, []):
        key = field_def["key"]
        fields.append({
            "key": key,
            "value": str(values.get(key, "")),
            "description": field_def.get("description", ""),
        })
    return fields


def _backup_config(module: str) -> None:
    """备份配置文件到 data/backup/config/。"""
    from ...cfgtoml import config_dir
    from ...config import get_settings
    settings = get_settings()
    src = config_dir() / f"{module}.toml"
    if not src.exists():
        return
    backup_dir = settings.data_dir / "backup" / "config"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    dst = backup_dir / f"{module}-{ts}.toml"
    shutil.copy2(src, dst)


def _save_module_config(module: str, form_data: dict) -> None:
    """把表单数据写回 toml 文件（键白名单：只接受该模块声明的字段）。"""
    from ...cfgtoml import config_dir

    toml_path = config_dir() / f"{module}.toml"
    allowed_keys = {f["key"] for f in _MODULE_FIELDS.get(module, [])}

    # 读取现有配置
    existing = {}
    if toml_path.exists():
        with open(toml_path, "rb") as f:
            existing = tomllib.load(f)

    # 更新字段：未在白名单内的表单键一律丢弃，防任意键注入
    for key, value in form_data.items():
        if key == "module" or key not in allowed_keys:
            continue
        # 尝试转换类型
        existing[key] = _convert_toml_value(value)

    # 写回 toml
    _write_toml(toml_path, existing)


def _convert_toml_value(value: str) -> str | int | float | bool:
    """尝试把字符串转换为合适的 TOML 类型。"""
    if not isinstance(value, str):
        return value
    # bool
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    # int
    try:
        return int(value)
    except ValueError:
        pass
    # float
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _escape_toml_string(value: str) -> str:
    """转义 TOML basic string 的特殊字符（反斜杠/引号/控制字符）。"""
    out = value.replace("\\", "\\\\")
    out = out.replace('"', '\\"')
    # 其余控制字符（含换行/制表）统一转成 \uXXXX，避免破坏行结构
    out = "".join(
        ch if ch >= " " else f"\\u{ord(ch):04X}" for ch in out
    )
    return out


def _write_toml(path: Path, data: dict) -> None:
    """简单的 TOML 写入（不依赖 toml 库；字符串必须转义防结构注入）。"""
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, str):
            lines.append(f'{key} = "{_escape_toml_string(value)}"')
        elif isinstance(value, bool):
            lines.append(f'{key} = {str(value).lower()}')
        elif isinstance(value, (int, float)):
            lines.append(f'{key} = {value}')
        else:
            lines.append(f'{key} = "{_escape_toml_string(str(value))}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
