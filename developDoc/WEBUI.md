# Aris WebUI（管理后台）

> **状态：设计定稿 v3（2026-08-23），实现待启动。** 定位为**内部管理后台**
> （运维者用），**不做网页对话**（对话走语音为主 + 外部平台如 Matrix/Discord）。
> TUI 定位为开发调试手段（见 AGENTS.md）。

## 定位与边界

给运维者用的控制面板：查看与操作 Aris 内部模块。读操作为主，部分写操作
（提供商增删、fetch 写回、技能增删改、配置保存）。

**做**：审计流水 / 提供商与模型管理（增删+fetch审核+退休） / 技能管理（增删改） /
配置管理 / 日志查看 / 系统状态 / 对话历史查看。

**不做**：网页对话。STT/TTS 管理、输出审核、插件管理——随对应模块落地。

**网络访问**：监听默认绑定 `0.0.0.0`（IPv4）+ `::`（IPv6），
即本机及局域网均可访问。**限制外部访问**：不暴露在公网，
只有通过同局域网或 VPN 才能连接。鉴权密码必设。

## 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | FastAPI + uvicorn | 异步、pydantic 已是依赖、表单/模板/静态齐备 |
| 模板 | Jinja2（服务端渲染） | `{% extends %}` + `{% include %}` 模板继承，公共组件（导航栏、页头）复用 |
| 前端交互 | htmx | 启停开关、fetch 审核勾选、页面局部刷新，无需 SPA |
| 样式 | UnoCSS（本地文件） | 从 CDN 下载到 `static/`，零构建步骤，原子化 CSS 写法，VitePress 风格简洁现代 |
| Markdown | marked.js（本地文件） | 从 CDN 下载到 `static/`，前端渲染 SKILL.md 全文，零 Python 依赖 |
| 实时 | SSE | 审计日志流 + 实时日志流推送 |
| 新增依赖 | `fastapi` / `uvicorn` / `jinja2` / `python-multipart` | 后两者：模板渲染 + 表单解析 |

> **为什么 CSS/JS 本地化而非 CDN**：本地工具没理由依赖外网，断网也能用。
> 从 CDN 下载 UnoCSS 全量 CSS（~300KB）+ marked.js（~50KB）到 `static/`，
> 零构建步骤意味着 `aris web` 一条命令启动。将来若页面增多可切 Vite 按需生成。

> **为什么用 Jinja2 模板继承而不用前端 include.js**：公共组件直接 Jinja2
> `{% extends "base.html" %}` + `{% include "nav.html" %}` 即可，
> 少维护一层前端依赖，数据渲染也在模板层完成。

## 模块结构

```
src/aris/webui/
├── __init__.py        # create_app() 工厂
├── auth.py            # 密码登录 + 7 天 session cookie（HMAC 签名，零依赖）
├── rate_limit.py      # 登录限流（内存计数器）
├── routes/
│   ├── dashboard.py   # 仪表盘（聚合统计 + 系统状态 + 快捷入口）
│   ├── audit.py       # 审计流水（查询/筛选 + SSE 实时流）
│   ├── providers.py   # 提供商管理（增删 + fetch 审核 + 退休管理）
│   ├── skills.py      # 技能管理（增删改 SKILL.md）
│   ├── config.py      # 配置管理（查看/编辑 config/*.toml）
│   ├── logs.py        # 日志查看（历史日志 + SSE 实时日志流）
│   └── history.py     # 对话历史（占位页，后续实现）
├── templates/
│   ├── base.html      # 基础骨架（导航栏 + head + footer）
│   ├── login.html
│   ├── dashboard.html
│   ├── audit.html
│   ├── providers.html
│   ├── skills.html
│   ├── config.html
│   ├── logs.html
│   └── history.html   # 占位页
└── static/
    ├── uno.css        # UnoCSS（从 CDN 下载）
    └── marked.min.js  # marked.js（从 CDN 下载）
```

CLI：`aris web --host 0.0.0.0 --port 9690`；host / port / session 天数进
`config/webui.toml`（cfgtoml 加载）。

## 页面清单（MVP，7 页）

| 页面 | 路由 | 功能 | 实时性 |
|---|---|---|---|
| 仪表盘 | `/` | 审计聚合统计 + 系统状态 + 各模块快捷入口卡片 | 按需刷新 |
| 审计流水 | `/audit` | 查询/筛选审计记录（按时间/模块/操作）、分页 | **部分实时**（SSE 日志流） |
| 提供商管理 | `/providers` | 提供方增删、模型列表、fetch 对比勾选写回、退休管理 | 按需刷新 |
| 技能管理 | `/skills` | 技能卡片列表、创建/编辑/删除 SKILL.md、查看全文（Markdown 渲染） | 按需刷新 |
| 配置管理 | `/config` | 查看/编辑 config/*.toml（表单）、.env 状态（只读） | 按需刷新 |
| 日志查看 | `/logs` | 历史日志文件浏览 + 实时日志流 | **部分实时**（SSE 日志流） |
| 对话历史 | `/history` | **占位页**（后续实现，待会话重新定义后补充） | — |

## 各页面详细设计

### 仪表盘 `/`

- 顶部统计卡片：今日对话数 / 提供商健康状态 / 活跃技能数 / 审计条目数
- 系统状态区域：各服务运行状态（LLM 连接、数据库连通性等）
- 下方快捷入口网格：提供商管理、审计、技能、配置、日志
- 简单聚合，不做图表（KISS）
- **提供商健康状态来源**：启动时 check 一次 + 运行中请求失败时被动更新

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
  - SKILL.md 内容展示（marked.js 前端渲染 Markdown）+ 编辑按钮
  - 编辑模式：textarea 在线编辑 + marked.js 实时预览，保存写回文件
  - 删除按钮（二次确认）
- 创建按钮：弹窗填 name / description，自动生成 SKILL.md 骨架并创建目录

### 配置管理 `/config`

- 左侧：模块列表（卡片）：chat / search / audit / logging / notify / webui
- 右侧：选中模块的配置表单（每个 key-value 一行：标签 + 输入框 + 当前值）
- 顶部：.env 状态（只读，显示 `ARIS_*` 变量名 + 是否已配置 ✅/❌，不显示值）
- 保存前自动备份旧配置到 `data/backup/config/<文件名>-<ISO时间戳>.toml`
- 保存后提示「重启生效」，不做自动热重载（后续评估）
- 密钥管理走终端，.env 不在 UI 中编辑
- 类型校验：根据 dataclass 字段类型校验（int/float/string）

### 日志查看 `/logs`

- 左侧：日期选择器 + 日志文件列表（`aris.log`、轮转文件 `.1` `.2` 等）
- 右侧：日志内容展示（等宽字体，按日志级别着色：ERROR 红 / WARNING 黄 / INFO 灰）
- 右上角「实时」按钮：开启 SSE 连接，新日志条目自动追加到底部
- 分页：每页 200 行，支持滚动加载
- 数据来源：`<data_dir>/logs/YYYY-MM-DD/aris.log`

### 对话历史 `/history`

- **占位页**：显示「后续实现」提示，待大会话机制落地后补充具体设计
- 后续将展示：按日期选择 → 展示当天所有小会话 → 按大会话分组的时间线视图
- 数据来源：`<data_dir>/logs/YYYY-MM-DD/<HH-MM-SS±时区>.jsonl`

## 鉴权（定案）

- 至少一个密码，一次登录 **7 天有效**。
- 密码来源：`.env` 的 `ARIS_WEBUI_PASSWORD`（密钥只进 .env）。
- 会话：登录成功签发 `aris_session` cookie（HMAC 签名令牌，payload 含
  签发时间 + 过期时间，`Max-Age=7 天`）；`/logout` 清除。
- **Cookie 安全属性**（2026-08-23 定案）：
  - `HttpOnly=True`：防 JS 读取 cookie
  - `SameSite=Lax`：防 CSRF，管理后台不需要跨站 POST
  - `Secure`：**不设**（无 HTTPS，设了浏览器会拒绝发送）
- **登录失败限流**（2026-08-23 定案）：
  - 5 分钟内允许 5 次失败，超限锁定 5 分钟
  - 内存计数器（单进程够用，重启清零——重启本身是运维操作）
  - 错误提示不暴露剩余次数（防枚举）
  - 不封 IP（LAN 环境，封了可能把自己锁在外面）
  - 不做验证码（KISS，LAN 环境没必要）
- 未配置密码时：登录页提示配置，**拒绝登录**（不裸奔），而非跳过鉴权。
- ⚠️ 默认绑定 `0.0.0.0` / `::`，网络可达——**密码必须设置**，否则等同暴露。
- 起步仅密码，无账号体系；未来如需可加 token / 更细权限。

## 逻辑复用（定案）

cli.py 里 `_cmd_llm_list / _cmd_llm_check / _cmd_llm_fetch / _cmd_llm_retired`
的逻辑嵌在 argparse + print + prompt_toolkit 里。**不拆 CLI**（能跑不动），
webui 直接调用底层模块（`load_providers`、`fetch.plan_sync / apply_sync /
load_retired`、`audit.query_recent / query_summary` 等），勾选 / 确认 / 渲染
换成页面交互。两套 UI 共享同一批底层函数，行为天然一致。

- 只读（list / check / audit / skills / config / logs / history）：先做。
- 写操作（provider 增删、fetch `--write`、skill 增删改、config 保存）：页面二次确认后直连底层函数。

## 配置

`config/webui.toml`（cfgtoml）：

```toml
host = "0.0.0.0"
port = 9690
session_days = 7
```

密码不在此文件——密钥一律 `.env`（`ARIS_WEBUI_PASSWORD`）。

**参数优先级**（2026-08-23 定案）：CLI 参数 > toml 配置 > 代码默认值。

## SSE 鉴权（定案）

- 审计日志流 + 实时日志流均为 SSE 长连接。
- 鉴权方式：**cookie**（与页面同源，浏览器自动携带，零额外代码）。
- HTMX `hx-sse` 扩展若默认不带 cookie，改用原生 `EventSource`
  （同源请求自动携带 cookie）。
- 不用 token query param（URL 暴露有日志泄露风险）。

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
2. 登录限流：连续 5 次错误密码后第 6 次被拒，等 5 分钟后恢复。
3. `/providers` 列表与 check 结果正确渲染（含密钥状态）。
4. fetch 流程：dry-run 展示 diff → 勾选 → 写回（用 mock provider 或本地
   临时 providers 文件，避免动真配置）。
5. `/skills` 列出真实 skill 并展示 SKILL.md 全文（marked.js 渲染）；
   创建/编辑/删除流程。
6. `/config` 读取 toml 配置并渲染表单，保存后文件内容正确，备份文件存在。
7. `/audit` SSE 实时日志流验证。
8. `/logs` 历史日志加载 + SSE 实时日志流验证。
9. `/history` 占位页正常显示。
10. 手动起服过一遍（默认绑定 0.0.0.0:9690，本机与局域网均可达）。

## 实现前置决策（2026-08-22 审查，2026-08-23 全部定案）

以下 8 项在设计审查中发现缺口，已全部定案：

| # | 事项 | 定案 |
|---|---|---|
| 1 | 对话历史格式 | JSON Lines，字段：ts/role/content/model/thinking/usage/tools，文件名 `HH-MM-SS±时区.jsonl` |
| 2 | Markdown 渲染 | marked.js 本地文件（前端渲染），SKILL.md 是可信内容，零 Python 依赖 |
| 3 | SSE 鉴权 | cookie（同源自动携带），不用 token query param |
| 4 | Cookie 安全属性 | HttpOnly=True + SameSite=Lax，不设 Secure（无 HTTPS） |
| 5 | 登录限流 | 5 次/5 分钟，内存计数器，重启清零 |
| 6 | 提供商健康状态 | 启动时 check 一次 + 运行中请求失败时被动更新 |
| 7 | --host/--port 优先级 | CLI > toml > 代码默认值 |
| 8 | plugins.html 模板 | 插件管理页面已移至「后续讨论」，占位页不需要 |

### 新增决策（2026-08-23）

| 事项 | 定案 |
|---|---|
| CSS/JS 本地化 | UnoCSS + marked.js 从 CDN 下载到 `static/`，断网可用 |
| 网络访问限制 | 限制外部访问，仅局域网/VPN 可连接 |
| 配置管理页面 | `/config`，表单编辑 config/*.toml，.env 只读，保存前备份到 data/backup |
| 日志查看页面 | `/logs`，历史日志浏览 + SSE 实时日志流 |
| 对话历史页面 | 占位页，待大会话机制落地后补充 |
| 热重载 | 先鸽，后续评估改动量 |

## 会话模型（2026-08-23 定案）

两层会话结构：

| 概念 | 定义 | 边界控制 | 文件对应 |
|---|---|---|---|
| **小会话** | 一段连续的对话（内存中的消息历史） | **自动**：上下文过长时 compact（总结→新会话保留摘要）并切新；`/new` 仅 TUI 调试手段（干净重来） | `HH-MM-SS±时区.jsonl` |
| **大会话** | 一组在时间上连续的小会话，「组内紧凑、组间有断点」 | **自动判断**（小会话间隔较长时切分） | 无直接文件对应，需运行时索引 |

关键点：
- 小会话边界也是自动的——上下文过长时系统自动 compact 并切新，用户无感
- **compact vs new 的区别**（2026-08-23 定案）：
  - compact（未实现）：总结当前上下文 → 新会话 = system prompt + compact 摘要（保留关键信息）
  - new：新会话 = 仅 system prompt（干净重来，丢弃所有上下文）
  - 自动 compact 走 compact 路径（保留上下文），不是 new
- `/new` 仅 TUI 调试手段，最终形态（STT→TTS）不需要
- 大会话不等于文件结构——文件按天分，大会话是逻辑分组
- 一个大会话里可能只有一个小会话（短对话），也可能很多（长对话）
- 大会话识别机制：程序根据小会话之间的间隔自动判断分组，需内存索引或元数据
- **大会话先不做**，当前按天 + 时间戳的文件结构够用
- 后续接入记忆系统时再实现大会话分组（记忆整理的触发边界）
- 两层边界都是自动的——用户（语音交互）完全不需要关心会话管理

## 后续讨论（未定事项）

1. 更细鉴权（token、角色）。
2. STT/TTS 管理、输出审核——随对应模块落地。
3. 插件管理——随插件系统落地。
4. 是否暴露 REST API 供移动端 / 其他客户端调用（现阶段页面直调内部函数，
   需要时再加 API 层）。
5. 前端交互升级（若页面复杂度上升，评估是否引入更多 JS 库）。
6. 配置热重载（保存 toml 后发信号让运行中模块重新读取）。
