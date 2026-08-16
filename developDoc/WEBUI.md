# Aris WebUI（管理后台）

> **状态：设计定稿（2026-08-16），实现待次日。** 定位为**内部管理后台**
> （运维者用），**不做网页对话**（TUI 已够用；网页对话是另一件事，另行评估）。
> 技术栈「基本可以，后续再讨论」，其余决策已定案（见下文标注）。

## 定位与边界

给运维者用的控制面板：查看与操作 Aris 内部模块。读操作为主，部分写操作
（fetch 写回、插件启停）。

**做**：审计流水 / 提供商与模型管理 / 技能管理 / 插件管理 / （占位）STT&TTS
管理 / （占位）输出审核。

**不做**：网页对话。监听默认绑定 `127.0.0.1`。

## 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | FastAPI + uvicorn | 异步、pydantic 已是依赖、表单/模板/静态齐备 |
| 前端 | 服务端渲染 Jinja2 + htmx | 管理后台全是表格/表单，SPA 无必要；零构建 |
| 交互 | 普通表单 + htmx（启停开关、写回确认） | 无需 SSE（无流式需求） |
| 新增依赖 | `fastapi` / `uvicorn` / `jinja2` / `python-multipart` | 后两者：模板渲染 + 表单解析 |

> 注：技术栈「后续再讨论」指是否引入更多前端工程化（如 htmx 升级为前端框架、
> 加图表库）另议，起步按上表。

## 模块结构

```
src/aris/webui/
├── __init__.py        # create_app() 工厂
├── auth.py            # 密码登录 + 7 天 session cookie（HMAC 签名，零依赖）
├── routes/            # audit.py / providers.py / skills.py / plugins.py（占位）
├── templates/         # Jinja2 页面
└── static/            # 一个 CSS，无构建
```

CLI：`aris web --host 127.0.0.1 --port 8000`；host / port / session 天数进
`config/webui.toml`（cfgtoml 加载）。

## 页面清单（MVP）

| 页面 | 数据来源 | 状态 |
|---|---|---|
| `/` 仪表盘 | 审计聚合（`query_summary`）+ 各模块快捷入口 | 实现 |
| `/audit` 审计流水 | `query_recent` / `query_summary`（bus 设计初衷） | 实现 |
| `/providers` 提供商&模型 | `load_providers`（列表/密钥状态/元数据）、check 体检、fetch 对比-勾选-写回、retired 管理 | 实现 |
| `/skills` 技能管理 | 扫描 skills/ 列全部 + 查看 SKILL.md 全文 | 实现（只读起步） |
| `/plugins` 插件管理 | PluginManager list / enable / disable | **依赖插件系统**，占位 |
| `/voice` STT/TTS 管理 | — | 占位（voice 模块后） |
| `/moderation` 输出审核 | — | 占位（以后再说） |

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

- 只读（list / check / audit / skills）：先做。
- 写操作（fetch `--write`、插件启停）：页面二次确认后直连底层函数。

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

## 验证计划（实现时）

1. pytest + FastAPI TestClient：未登录跳登录页、密码错误拒绝、登录成功发
   cookie、7 天有效期（校验签名与过期）、各页面 200。
2. `/providers` 列表与 check 结果正确渲染（含密钥状态）。
3. fetch 流程：dry-run 展示 diff → 勾选 → 写回（用 mock provider 或本地
   临时 providers 文件，避免动真配置）。
4. `/skills` 列出真实 skill 并展示 SKILL.md 全文。
5. 手动起服过一遍（绑定 127.0.0.1）。

## 后续讨论（未定事项）

1. 前端工程化升级（htmx → 前端框架 / 图表库）另议。
2. 更细鉴权（token、角色、CSRF 防护策略）。
3. `/plugins`、`/voice`、`/moderation` 随对应模块落地。
4. 是否暴露 REST API 供移动端 / 其他客户端调用（现阶段页面直调内部函数，
   需要时再加 API 层）。
