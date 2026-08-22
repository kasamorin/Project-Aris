# Aris WebUI（管理后台）

> **状态：设计定稿 v2（2026-08-22），实现待启动。** 定位为**内部管理后台**
> （运维者用），**不做网页对话**（对话走语音为主 + 外部平台如 Matrix/Discord）。
> TUI 定位为开发调试手段（见 AGENTS.md）。

## 定位与边界

给运维者用的控制面板：查看与操作 Aris 内部模块。读操作为主，部分写操作
（提供商增删、fetch 写回、技能增删改、插件启停）。

**做**：审计流水 / 提供商与模型管理（增删+fetch审核+退休） / 技能管理（增删改） /
对话历史查看 / （占位）STT&TTS 管理 / （占位）输出审核。

**不做**：网页对话。监听默认绑定 `127.0.0.1`。

## 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | FastAPI + uvicorn | 异步、pydantic 已是依赖、表单/模板/静态齐备 |
| 模板 | Jinja2（服务端渲染） | `{% extends %}` + `{% include %}` 模板继承，公共组件（导航栏、页头）复用 |
| 前端交互 | htmx | 启停开关、fetch 审核勾选、页面局部刷新，无需 SPA |
| 样式 | UnoCSS CDN（runtime） | 零构建步骤，一行 `<script>` 引入，原子化 CSS 写法，VitePress 风格简洁现代 |
| 实时 | SSE | 审计日志流推送（仅审计页面需要） |
| 新增依赖 | `fastapi` / `uvicorn` / `jinja2` / `python-multipart` | 后两者：模板渲染 + 表单解析 |

> **为什么用 UnoCSS CDN 而非 Vite 构建**：管理后台是本机单人用，页面只有 6 个，
> CDN 全量 CSS（~300KB）无性能影响。零构建步骤意味着 `aris web` 一条命令启动，
> 不需要额外构建链。将来若页面增多可切 Vite 按需生成。

> **为什么用 Jinja2 模板继承而不用前端 include.js**：公共组件直接 Jinja2
> `{% extends "base.html" %}` + `{% include "nav.html" %}` 即可，
> 少维护一层前端依赖，数据渲染也在模板层完成。

## 模块结构

```
src/aris/webui/
├── __init__.py        # create_app() 工厂
├── auth.py            # 密码登录 + 7 天 session cookie（HMAC 签名，零依赖）
├── routes/
│   ├── dashboard.py   # 仪表盘（聚合统计 + 快捷入口）
│   ├── audit.py       # 审计流水（查询/筛选 + SSE 实时流）
│   ├── providers.py   # 提供商管理（增删 + fetch 审核 + 退休管理）
│   ├── skills.py      # 技能管理（增删改 SKILL.md）
│   ├── history.py     # 对话历史（按日期浏览，只读）
│   └── plugins.py     # 插件管理（占位）
├── templates/
│   ├── base.html      # 基础骨架（导航栏 + head + footer）
│   ├── dashboard.html
│   ├── audit.html
│   ├── providers.html
│   ├── skills.html
│   ├── history.html
│   └── login.html
└── static/
    └── (UnoCSS 通过 CDN 引入，无需本地静态文件)
```

CLI：`aris web --host 127.0.0.1 --port 8000`；host / port / session 天数进
`config/webui.toml`（cfgtoml 加载）。

## 页面清单（MVP，6 页）

| 页面 | 路由 | 功能 | 实时性 |
|---|---|---|---|
| 仪表盘 | `/` | 审计聚合统计 + 各模块快捷入口卡片 | 按需刷新 |
| 审计流水 | `/audit` | 查询/筛选审计记录（按时间/模块/操作）、分页 | **部分实时**（SSE 日志流） |
| 提供商管理 | `/providers` | 提供方增删、模型列表、fetch 对比勾选写回、退休管理 | 按需刷新 |
| 技能管理 | `/skills` | 技能卡片列表、创建/编辑/删除 SKILL.md、查看全文 | 按需刷新 |
| 对话历史 | `/history` | 按日期选择器浏览历史对话（气泡列表），只读 | 按需刷新 |
| 插件管理 | `/plugins` | **占位**（依赖插件系统落地） | — |

## 各页面详细设计

### 仪表盘 `/`

- 顶部统计卡片：今日对话数 / 提供商健康状态 / 活跃技能数 / 审计条目数
- 下方快捷入口网格：提供商管理、审计、技能、对话历史
- 简单聚合，不做图表（KISS）

### 审计 `/audit`

- 主体：表格（时间 / 模块 / 操作 / 结果 / 详情）
- 筛选栏：时间范围、模块下拉、操作类型
- 分页：每页 50 条
- 右上角「实时」按钮：开启 SSE 连接，新审计条目自动追加到表格顶部

### 提供商管理 `/providers`

- 左侧面板：提供方列表（卡片式），每个卡片显示名称、密钥状态（✅/❌）、模型数量
- 右侧面板：选中提供方的详情
  - **模型列表**：表格（id / name / context / capabilities / thinking_default），支持排序
  - **添加提供方**：弹窗表单（id / name / base_url / api_key_env）
  - **删除提供方**：二次确认后删除
  - **fetch 审核**：点击「同步模型」→ 显示 dry-run diff（新增/保留/退休列表）→ 勾选确认 → 写回
  - **退休管理**：独立 tab，列出退休模型（provider / model / first_missing / 宽限期剩余天数），支持手动删除

### 技能管理 `/skills`

- 卡片网格：每个 skill 一张卡（name / description / 启用状态）
- 点击进入详情页：
  - SKILL.md 内容展示（Markdown 渲染）+ 编辑按钮
  - 编辑模式：textarea 在线编辑，保存写回文件
  - 删除按钮（二次确认）
- 创建按钮：弹窗填 name / description，自动生成 SKILL.md 骨架并创建目录

### 对话历史 `/history`

- 左侧：日期选择器（日历控件或下拉列表，列出有记录的日期）
- 右侧：对话气泡列表（用户消息靠右 / Aris 回复靠左），按时间排列
- 只读，不需要编辑/删除功能
- 数据来源：`<data_dir>/logs/YYYY-MM-DD/chat.log`

## 鉴权（定案）

- 至少一个密码，一次登录 **7 天有效**。
- 密码来源：`.env` 的 `ARIS_WEBUI_PASSWORD`（密钥只进 .env）。
- 会话：登录成功签发 `aris_session` cookie（HMAC 签名令牌，payload 含
  签发时间 + 过期时间，`Max-Age=7 天`）；`/logout` 清除。
- 未配置密码时：登录页提示配置，**拒绝登录**（不裸奔），而非跳过鉴权。
- 起步仅密码，无账号体系；未来如需可加 token / 更细权限。

## 逻辑复用（定案）

cli.py 里 `_cmd_llm_list / _cmd_llm_check / _cmd_llm_fetch / _cmd_llm_retired`
的逻辑嵌在 argparse + print + prompt_toolkit 里。**不拆 CLI**（能跑不动），
webui 直接调用底层模块（`load_providers`、`fetch.plan_sync / apply_sync /
load_retired`、`audit.query_recent / query_summary` 等），勾选 / 确认 / 渲染
换成页面交互。两套 UI 共享同一批底层函数，行为天然一致。

- 只读（list / check / audit / skills / history）：先做。
- 写操作（provider 增删、fetch `--write`、skill 增删改、插件启停）：页面二次确认后直连底层函数。

## 配置

`config/webui.toml`（cfgtoml）：

```toml
host = "127.0.0.1"
port = 8000
session_days = 7
```

密码不在此文件——密钥一律 `.env`（`ARIS_WEBUI_PASSWORD`）。

## 接入点

- CLI 子命令 `aris web`：构造 `create_app()` 后 uvicorn.run。
- 路由按需构造依赖（`get_settings()`、`load_providers()`），不共享会话状态
  （管理后台无状态请求，无需会话对象）。

## UI 设计风格

- **浅色主题**，简洁现代（VitePress 风格：大留白、清晰层级、柔和配色）
- **左侧固定导航栏** + 右侧内容区
- 组件：表格、表单、卡片、开关、按钮、弹窗
- 图标：Lucide（SVG sprite，轻量）
- 响应式：基础适配（本机用为主，不急需但要做）

## 验证计划（实现时）

1. pytest + FastAPI TestClient：未登录跳登录页、密码错误拒绝、登录成功发
   cookie、7 天有效期（校验签名与过期）、各页面 200。
2. `/providers` 列表与 check 结果正确渲染（含密钥状态）。
3. fetch 流程：dry-run 展示 diff → 勾选 → 写回（用 mock provider 或本地
   临时 providers 文件，避免动真配置）。
4. `/skills` 列出真实 skill 并展示 SKILL.md 全文；创建/编辑/删除流程。
5. `/audit` SSE 实时日志流验证。
6. `/history` 按日期加载对话记录。
7. 手动起服过一遍（绑定 127.0.0.1）。

## 后续讨论（未定事项）

1. 更细鉴权（token、角色、CSRF 防护策略）。
2. `/plugins`、`/voice`、`/moderation` 随对应模块落地。
3. 是否暴露 REST API 供移动端 / 其他客户端调用（现阶段页面直调内部函数，
   需要时再加 API 层）。
4. 前端交互升级（若页面复杂度上升，评估是否引入更多 JS 库）。
