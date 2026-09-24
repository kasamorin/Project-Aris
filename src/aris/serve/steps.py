"""serve 的启动步骤表：每一步的探针（只读）与启动动作。

三类步骤（见 developDoc/SERVE.md 第 2 节）：

- ① **import 即就绪**（core / persona / behavior）：``start=None``，探针只做自检
- ② **需要外部资源**（store.db / store.embed / knowledge）：启动动作由模块自己经
  总线提供（``store.start`` / ``store.embed_preload`` / ``knowledge.start``）
- ③ **入口**（webui）：``blocks=True``，由编排方在打完启动清单后调用（它会阻塞
  到 Ctrl-C）

步骤顺序 = :func:`build_steps` 返回的列表顺序；新增步骤只改本文件。
探针**只读**（不启动任何东西），失败即抛异常——serve 据此打印 `✗` 并按档位处理。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..config import get_settings
from ..core import call, has_service
from .conf import ServeConfig


@dataclass(frozen=True)
class ServeStep:
    """一个启动步骤。"""

    name: str
    label: str
    probe: Callable[[], str]
    level: str = "optional"  # required / optional（required 失败会让依赖它的步骤跳过）
    start: Callable[[], str] | None = None  # None = import 即就绪，无启动动作
    needs: tuple[str, ...] = ()  # 依赖的步骤名（--only 会自动补齐）
    blocks: bool = False  # True = 阻塞步骤（WebUI），编排方最后调用


def _probe_services() -> str:
    """探针：组装后的服务表是否覆盖各模块声明的依赖（缺一即报，不静默）。

    清单由各模块自己声明（如 `webui.REQUIRED_SERVICES`），serve 只负责启动时统一
    核验——原实现散在 `webui.create_app()` 里，只有 WebUI 那条路径会被检查。
    """
    from ..webui import REQUIRED_SERVICES

    missing = [name for name in REQUIRED_SERVICES if not has_service(name)]
    if missing:
        raise RuntimeError(
            f"缺少服务：{', '.join(missing)}——检查组装根是否 import 到了所有者模块"
        )
    return f"各模块声明的 {len(REQUIRED_SERVICES)} 个依赖服务全部就绪"


def _probe_llm() -> str:
    """探针：LLM 配置可读、有可用提供方、体检无错误、审计与 http 服务已注册。"""
    from ..core.llm import load_providers

    config = load_providers(get_settings().llm_providers_file)
    if not config.providers:
        raise RuntimeError("providers.toml 里没有可用提供方，请检查 config/providers.toml")
    models = sum(len(p.models) for p in config.providers)
    default = config.default_model or "未设"
    missing = [s for s in ("audit.recent", "audit.summary", "http.request") if not has_service(s)]
    if missing:
        raise RuntimeError(f"缺少服务：{', '.join(missing)}")
    issues = call("llm.providers.check") or []
    errors = [message for level, message in issues if level == "error"]
    if errors:
        raise RuntimeError(f"LLM 配置 {len(errors)} 个错误：{errors[0]}（详情 `aris llm check`）")
    warnings = len(issues) - len(errors)
    tail = f"；{warnings} 个警告" if warnings else ""
    return f"{len(config.providers)} 个提供方 / {models} 个模型，默认 {default}{tail}"


def _probe_persona() -> str:
    """探针：人设服务已注册。"""
    if not has_service("persona.system_prompt"):
        raise RuntimeError("persona.system_prompt 未注册")
    return "system_prompt 已注册"


def _probe_behavior() -> str:
    """探针：技能服务已注册。

    注意：工具注册表（``tools.execute``）、agent loop（``loop.run``）、
    ``skills.menu`` 都是**实例级**服务，由会话对象（`ChatSession`）自建，
    这里只校验 import 级注册（serve 目前不持有会话，将来多人格/自动任务时再上收）。
    """
    if not has_service("skills.list"):
        raise RuntimeError("skills.list 未注册")
    return "skills 服务已注册（工具与 loop 按需构造）"


def _probe_db(init_if_missing: bool) -> str:
    """探针：数据库实例是否存在、是否在跑、有多少待执行迁移（不启动）。"""
    info: dict[str, Any] = call("store.db_status") or {}
    if not info:
        raise RuntimeError("store.db_status 未注册")
    if not info.get("installed"):
        if init_if_missing:
            return f"未初始化（启动时将自动获取，需联网）@127.0.0.1:{info['port']}"
        raise RuntimeError("便携数据库尚未初始化：执行 `aris db init`")
    if not info.get("running"):
        return f"未运行（启动时将自启）@127.0.0.1:{info['port']}"
    pending = len(info.get("pending_migrations") or [])
    return f"PG 运行中 @127.0.0.1:{info['port']}；待执行迁移 {pending} 条"


def _start_db(autostart: bool, init_if_missing: bool) -> str:
    """启动动作：确保数据库可用（缺则自建）并应用迁移。"""
    info: dict[str, Any] = call(
        "store.start", autostart=autostart, init_if_missing=init_if_missing
    ) or {}
    if not info:
        raise RuntimeError("store.start 未注册")
    if info.get("created"):
        origin = "本次自建并自启"
    elif info.get("started_by_serve"):
        origin = "本次自启"
    elif info.get("running_before"):
        origin = "复用已在运行的实例"
    else:
        origin = "已就绪"
    migrations = len(info.get("migrations") or [])
    return f"PG @127.0.0.1:{info['port']}（{origin}）；应用迁移 {migrations} 条"


def _probe_embed() -> str:
    """探针：embedding 配置与预热状态（不触发加载）。"""
    dimension = call("store.embed_dimension")
    state: dict[str, Any] = call("store.embed_status") or {}
    return f"{dimension} 维；{state.get('detail', state.get('status', 'idle'))}"


def _start_embed() -> str:
    """启动动作：后台预热 embedding（立即返回，不等加载完）。"""
    state: dict[str, Any] = call("store.embed_preload") or {}
    if not state:
        raise RuntimeError("store.embed_preload 未注册")
    return f"{state.get('detail', '')}（后台预热，不阻塞启动）"


def _probe_knowledge() -> str:
    """探针：知识库开关与文档/块计数（库不可用时抛错，不静默降级）。

    PG 未运行时不算失败——真实启动时 store.db 会先把它拉起来，故此处只报
    「待数据库启动后建表」，否则 dry-run 会误报一片红。
    """
    info: dict[str, Any] = call("knowledge.status") or {}
    if not info:
        raise RuntimeError("knowledge.status 未注册")
    if not info.get("enabled", True):
        return "已关闭（config/knowledge.toml: enabled=false）"
    db: dict[str, Any] = call("store.db_status") or {}
    if not db.get("running"):
        return "待数据库启动后建表（PG 未运行）"
    if info.get("error"):
        raise RuntimeError(str(info["error"]))
    return f"{info.get('docs', 0)} 文档 / {info.get('chunks', 0)} 块"


def _start_knowledge() -> str:
    """启动动作：建表 / 建索引 / 统计（幂等）。"""
    info: dict[str, Any] = call("knowledge.start") or {}
    if not info:
        raise RuntimeError("knowledge.start 未注册")
    if not info.get("enabled", True):
        return "已关闭（config/knowledge.toml: enabled=false）"
    return f"{info.get('docs', 0)} 文档 / {info.get('chunks', 0)} 块，索引已就绪"


def _probe_webui() -> str:
    """探针：监听端口是否可用（被占用即抛错，交由档位处理）。"""
    info: dict[str, Any] = call("webui.probe") or {}
    if not info:
        raise RuntimeError("webui.probe 未注册")
    if not info.get("available", False):
        raise RuntimeError(
            f"端口 {info.get('host')}:{info.get('port')} 已被占用"
            "（可能已有 `aris web` / `aris serve` 在运行）"
        )
    mode = "免鉴权：仅本机" if info.get("warning") else "已配密码"
    return f"http://{info['host']}:{info['port']}（{mode}）"


def _start_webui() -> str:
    """启动动作：拉起 WebUI（**阻塞**，直到 Ctrl-C）。"""
    return str(call("webui.start") or "")


def build_steps(config: ServeConfig) -> list[ServeStep]:
    """按配置生成步骤表（列表顺序 = 启动顺序）。"""
    embed_start = _start_embed if config.preload_embedding else None
    return [
        ServeStep("services", "services", _probe_services, level="required"),
        ServeStep("core", "core.llm", _probe_llm),
        ServeStep("persona", "persona", _probe_persona),
        ServeStep("behavior", "behavior", _probe_behavior),
        ServeStep(
            "store.db",
            "store.db",
            lambda: _probe_db(config.init_db),
            level="required",
            start=lambda: _start_db(config.start_db, config.init_db),
        ),
        ServeStep("store.embed", "store.embed", _probe_embed, start=embed_start),
        ServeStep(
            "knowledge",
            "knowledge",
            _probe_knowledge,
            start=_start_knowledge,
            needs=("store.db",),
        ),
        ServeStep("webui", "webui", _probe_webui, start=_start_webui, blocks=True),
    ]


__all__ = ["ServeStep", "build_steps"]
