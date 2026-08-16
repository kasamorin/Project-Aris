# Aris 插件（Plugin）系统

> **状态：草案（2026-08-16）。** 本文是插件系统的设计蓝图。多处决策标注
> `[待讨论]`，未定案前不实现。定案后更新本文（划掉对应条目）再开发。
> 当前代码库中**尚无任何插件系统代码**。

## 背景与由来

Aris 需要接入外部服务（如 AstrBook AI 论坛）。2026-08-16 已论证：

- 原样 skill（纯 curl 指令式手册）**不可用**——模型只能调注册式工具，
  没有通用 shell / curl 工具（详见 `SKILLS.md` 与 AstrBook 调研结论）。
- 方向定为**独立插件模块**（用户拍板）：插件 = 用户显式启用的外部服务
  集成包。插件系统只提供机制（发现 / 生命周期 / 装载），具体适配
  （工具、手册、凭据）全部装进插件。

与既有能力的关系：

| | Skill | **Plugin（新）** | MCP |
|---|---|---|---|
| 谁触发装载 | 模型按需激活 | **用户显式启用**（生命周期管理） | 外部进程 |
| 形态 | SKILL.md + tools.py | plugin.toml + plugin.py + 可选 SKILL.md | 服务器 |
| 目的 | 轻量能力 | 外部服务集成包 | 未来工具来源 |
| 归属 | behavior/skills/ | **独立模块 plugins/** | 未来工具来源 |

插件与 skill 并行不悖：skill 是模型按需调用的轻量能力；plugin 是用户主动
启用的外部服务集成。二者共用 `ToolRegistry`，装载方式上互不耦合。

## 模块结构（草案）

```
src/aris/plugins/            # 独立包（平行于 core/behavior/chat）[待讨论]
├── __init__.py              # 导出 PluginManager
├── manifest.py              # plugin.toml 解析（dataclass + tomllib）
├── manager.py               # 发现 / 装载 / 启用 / 禁用 / 激活（核心）
└── astrbook/                # 首方插件（进 git）
    ├── plugin.toml          # manifest
    ├── plugin.py            # hooks：register(registry) / setup(ctx)
    └── SKILL.md             # 使用手册（可激活披露）
```

外部安装插件（zip → `data/plugins/<name>/`）`[待讨论]`：v1 暂缓（YAGNI）。

## 插件形态（草案）

**manifest（plugin.toml）**

```toml
name = "astrbook"
version = "0.1.0"
description = "接入 AstrBook AI 论坛：浏览/搜索/发帖/回帖/通知"
author = "aris"
load = "lazy"                # eager / lazy [待讨论]
```

**hooks（plugin.py，均可选）**
- `register(registry)`：注册工具（复用 `ToolRegistry`，与 skill 的
  `tools.py` 同形态）。
- `setup(ctx)`：注册 core 服务 / 初始化；ctx 提供 `name / path /
  data_dir / config`。

## 装载时机 [待讨论]

- `load = "eager"`：启用即注册工具 → 工具定义常驻每个请求（token 换便利）。
- `load = "lazy"`：启用后进**插件菜单**（注入 system prompt，仿
  `skills.menu`），模型调 `activate_plugin("astrbook")` 装载工具 + 返回
  手册 → 工具不常驻、省 token（与 skill 按需激活同思路）。

倾向：AstrBook 用 lazy。是否做成 manifest 字段二选一未定。

## 激活入口 [待讨论]

- 方案 A：独立 `activate_plugin`，插件菜单与技能菜单并存、互不耦合
  （符合「独立模块」定位）。
- 方案 B：复用 `activate_skill`，插件手册并入技能菜单（机制更少，但
  插件与 skill 边界变模糊）。

## 生命周期与 CLI

- 状态记录：`config/plugins.toml`（`enabled = [...]`，进 git 默认空）。
- 命令：
  ```
  aris plugin list                # 发现全部（含未启用）：名称/版本/描述/状态/load
  aris plugin enable <name>       # 启用（写状态）
  aris plugin disable <name>      # 禁用
  ```
- `install / uninstall`（zip 安装）暂缓 [待讨论]。

## 数据 / 配置 / 密钥约定（沿用三源收口）

- 持久化数据：`data/plugins/<name>/`
- 可调参数：`config/<name>.toml`（dataclass + `cfgtoml` 加载）
- 密钥：`.env`（如 `ASTRBOOK_API_BASE` / `ASTRBOOK_TOKEN`）

## 接入点

`chat/session.py` 构造（启用工具时）创建 `PluginManager(registry)`：装载
eager 插件 + 注入插件菜单。CLI 命令不依赖会话（直接操作 manifest / 状态）。

## 验证计划（实现时）

1. manifest 解析 / 发现（builtin + 损坏容错）/ 状态读写
2. eager 注册、lazy 激活（幂等、不存在容错）
3. register / setup 钩子、data_dir / config 注入
4. CLI list / enable / disable 端到端
5. 先用一个极简 demo 插件验证机制，再上 astrbook 真实插件

## 后续：AstrBook 插件（占位）

插件系统定案后细化。拟定内容：
- 工具：`astrbook_browse / search / trending / read / notifications` +
  `post / reply / sub_reply / like`，全走 `core.call("http.request")`
  （可审计、复用命名会话与 cookie 连续性）。
- SKILL.md：中文短手册（≤500 行 / 5000 token）。
- 凭据：`.env` 的 `ASTRBOOK_API_BASE` / `ASTRBOOK_TOKEN`。
- 测试：本地 reference server（`~/Codes/Project-Aris-Reference/astrbook/`）
  或真实 API。

---

# 后续讨论（每条定案后划掉）

1. **模块位置**：`src/aris/plugins/` 独立包（平行于 behavior/core/chat）vs
   `core/plugins/`。倾向独立包——插件主要承载行为扩展，放 core 语义偏窄。
2. **装载时机**：eager / lazy / manifest 字段二选一。倾向 lazy（省 token，
   与 skill 按需激活同思路）；是否支持 eager 常驻待定。
3. **激活入口**：独立 `activate_plugin`（倾向）vs 复用 `activate_skill`。
4. **生命周期范围**：list / enable / disable 起步；install / uninstall
   （zip → `data/plugins/`）何时做待定。
5. **状态文件**：`config/plugins.toml`（进 git 默认空，用户/命令改）vs
   `data/`。倾向 config——启用是用户决策，非运行时数据。
6. **外部插件安装**：zip 安装、版本/依赖声明（pip 依赖）、卸载清理。
7. **安全边界**：插件是代码，与 Aris 同权限（同 skill tools.py 现状）。
   是否需要额外约束（如禁止 io / 网络、审计增强）或沙箱，按信任级别讨论。
8. **插件与 WebUI**：`/plugins` 管理页依赖本系统落地（见 `WEBUI.md`）。
