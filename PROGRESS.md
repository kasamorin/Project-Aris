# 开发进度

> 每次开发前先读本文件，了解最新状态。

## 当前版本：v0.3.0

## 最新状态

### 2026-08-30：WebUI 安全审查 + 总线化改造 + 防复发机制

**背景：** 接手被部分废弃的 v0.3.0 WebUI 代码，按用户决策顺序收尾：
修复安全/规范问题 → 总线化 → 补测试 → 流程防复发 → 回归记忆系统主线。

**安全修复（已合并回 develop）：**
- 路径穿越：技能删除/日志读取/配置模块参数/技能名 `..` 均可越界读写 → 全部根治
- TOML 注入：providers 改 tomli_w 结构化写回；config 手写 toml 补全转义 + 键白名单
- XSS：marked.js 输出经 DOMPurify 净化；SSE `innerHTML` 注入 → 事件流改 `tojson`+文本节点
- 鉴权绕过：`/login` 前缀宽匹配（`/loginfoo` 可绕过）→ 精确集合 + 前缀分离
- 业务缺陷：审计页时间戳全显当前时间、分页失效 → 修正（`AuditRecord.wall_ts`）
- 静默吞异常 → 记 loguru warning；provider 重定向错误 URL 拼接修复
- 技能目录从 CWD 相对路径改为包内绝对路径 `SKILLS_DIR`

**总线化改造（严格 core.call，已合并）：**
- 新增 16 个总线服务：`llm.providers.*`（manage.py）/ `llm.fetch.*`+`llm.retired.*`
  （fetch.py）/ `skills.*`（manager.py）/ `audit.recent`+`audit.summary`（bus.py）
- webui 全部 9 个路由改走 `core.call`，消灭对 core.llm/core.audit/behavior.skills 直连
- `create_app()` 触发注册 + `_verify_bus_services()` 启动自检（`bus.has_service`）
- 基础设施例外（记入 BUS-ARCHITECTURE.md）：`get_settings` / `cfgtoml` 直连不算模块间通讯

**测试与防复发：**
- 新增 tests/test_webui.py 11 用例：auth / 限流 / config 写回 / skills CRUD 全链路，
  全部隔离到 tmp_path；`uv run pytest` **48 passed**
- `.githooks/pre-commit`：main 禁非合并提交、develop 直提警告（三场景已实测）
- `scripts/release-check.sh`：版本三源一致 + develop 分支 + 无未合并分支检查
- AGENTS.md / BUS-ARCHITECTURE.md / SECURITY-AND-REFACTOR-PLAN.md 已同步

**偏差存档（用户决策）：**
- 历史提交（v0.2.6/v0.3.0 默认 merge message、WebUI 直落 develop）**保持原样不重写**
- `config.toml.read/write` 未走总线（属配置系统基础设施，记为明文例外）
- 审计查询跳过总线与否由 `audit.*` 服务统一封装，路由不感知

**下一步：** 回归主线——记忆系统（PostgreSQL + pgvector）。

### 2026-08-23：WebUI 管理后台完成（v0.3.0）

**已完成：**
- FastAPI 应用工厂 + 路由注册
- 登录鉴权（HMAC cookie + 限流 5次/5分钟）
- 仪表盘（统计卡片 + 快捷入口）
- 审计流水（表格展示 + 筛选 + 分页 + SSE 实时流）
- 提供商管理（列表 + 模型详情 + 增删 + fetch 审核 + 退休管理）
- 技能管理（列表 + 详情 + 创建/编辑/删除 + marked.js 渲染）
- 配置管理（表单编辑 toml + .env 只读 + 保存前备份）
- 日志查看（文件浏览 + 分页 + SSE 实时流）
- 对话历史（占位页）
- 响应式布局
- 请求日志中间件

**新增依赖：**
- fastapi / uvicorn / jinja2 / python-multipart

**待完成（记录待办）：**
- 仪表盘系统状态区域
- htmx 引入（可选）
- Lucide 图标（可选）

## 开发路线

1. ✅ 搭标准项目骨架（2026-08）
2. ✅ 接入 LLM（2026-08-09）
3. ✅ 跑通文字对话（2026-08-09）
4. 记忆系统（PostgreSQL + pgvector）—— **下一步**
5. ✅ 人格系统（提示词工程起步，2026-08-12）
6. 语音链路（STT → LLM → TTS）
7. ✅ 行为扩展（函数调用 2026-08-09，联网搜索 2026-08-09）
8. GraphRAG

## 当前聚焦

**记忆系统**（PostgreSQL + pgvector）
- WebUI 管理后台已完成（v0.3.0，2026-08-23）
