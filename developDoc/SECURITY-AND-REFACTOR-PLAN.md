# WebUI 安全审查与总线化重构计划

> 起因：v0.2.6 / v0.3.0 由 mimo（AI agent）开发，绕过流程规范直接在 develop 上提交，
> 大量代码未经评审即合入主干。接手后制定本计划，逐步消除技术债。

---

## 一、v0.2.5 → v0.2.6 → v0.3.0 流程审查结论

### 符合规范

- [x] 三个 tag 存在且已推远程，均打在 main 的合并提交上
- [x] main 只进版本发布，日常 fix/docs 未直接进 main
- [x] 版本号三源同步一致（pyproject.toml / `__init__.py` / uv.lock）
- [x] v0.2.6→v0.3.0 大功能 WebUI bump minor（正确）
- [x] 提交信息 head 符合 Conventional Commits
- [x] 无 .env / data/ 文件泄漏
- [x] 代码抽查：中文注释/docstring、英文命名、行宽 ≤100

### 违规 / 偏差（已记录，不重写历史）

| # | 严重程度 | 问题 | 涉及版本 |
|---|---------|------|----------|
| 1 | 严重 | WebUI ~13 个提交直落 develop，无 feature 分支 + `--no-ff` 合并 | v0.3.0 |
| 2 | 严重 | main 合并提交信息均为默认 `Merge branch 'develop'`，未按规范写摘要 | v0.2.5/v0.2.6/v0.3.0 |
| 3 | 中等 | v0.3.0 bump 用 `docs:` 前缀且混入文档改动（惯例独立 `build: 版本 X`） | v0.3.0 |
| 4 | 轻微 | v0.2.6 build 漏同步 uv.lock，需补 chore 提交 | v0.2.6 |
| 5 | 轻微 | feat/sampling-params 分支混入无关 WebUI 文档提交 | v0.2.6 |
| 6 | 轻微 | 三个 tag 为轻量标签（非 annotated，规范未强制） | 全部 |

---

## 二、WebUI 代码安全审查（fix/webui-audit 分支）

### 已修复（12 个文件，pytest 37 passed）

| 分类 | 严重程度 | 问题 | 修复方式 |
|------|---------|------|----------|
| 路径穿越 | 🔴 严重 | `skills/{name}` 未校验，`name=".."` 可 rmtree 删父目录 | `re.fullmatch` + resolve() 双保险 + 技能目录改用包内路径（不再依赖 CWD） |
| 任意文件读 | 🔴 严重 | `logs?file=../../etc/passwd` 读任意文件 | date 白名单 `\d{4}-\d{2}-\d{2}`；file 拒绝分隔符 + resolve 目录包含校验 |
| TOML 注入 | 🔴 严重 | providers 四个写函数用字符串拼装，可注入恶意 TOML | 全部改用 tomllib 读 + tomli_w 结构化写（与 fetch.py 写回方式一致） |
| TOML 转义 | 🟠 中等 | `config._write_toml` 字符串未转义，含引号的值破坏文件 | 新增 `_escape_toml_string` 处理反斜杠/引号/控制字符 |
| config 穿越 | 🔴 严重 | `module` 参数未白名单校验，可写任意 toml 到 config_dir 之外 | 入口处校验 `module in _MODULES` |
| 键注入 | 🟠 中等 | `config_save` 接受任意表单键写入 toml | 只写 `_MODULE_FIELDS` 声明的键，其余丢弃 |
| XSS | 🔴 严重 | `marked.parse()` 无净化直接 innerHTML（skill_detail/edit） | 引入 DOMPurify；两处渲染均经 `DOMPurify.sanitize()` |
| XSS SSE | 🟠 中等 | `audit.html` SSE 数据直接拼 innerHTML | 新增 `escText()` HTML 转义函数 |
| onclick 注入 | 🟠 中等 | `deleteSkill('{{skill.name}}')` Jinja 未转义 | 改为 `\| tojson` filter |
| 审计时间假 | 🟠 中等 | 所有记录显示当前时间（`time.strftime`） | core AuditRecord 新增 `wall_ts` 字段，显示真实墙钟 |
| 分页失效 | 🟠 中等 | audit page 参数被忽略，永远显示第 1 页 | 实现真实分页切片：先拉后切窗口 |
| 静默异常 | 🟡 轻微 | providers 多处 `except: pass` | 改为 `logger.warning` 保留排查线索 |
| 公开路径过宽 | 🟡 轻微 | `_PUBLIC_PATHS` 用 `startswith`，`/loginfoo` 等绕过鉴权 | 拆分精确匹配 `/login` + 前缀匹配 `/static/` |
| redirect 注入 | 🟡 轻微 | 错误消息直接拼 URL query，特殊字符破坏格式 | 统一用 `urllib.parse.quote` 编码 |

### 已知遗留（阶段三处理）

- skills.providers 直接 import `core.llm` / `config` 绕过总线规则 → **阶段二解决**
- SKILLS_DIR 从包内引入（解决了 CWD 问题），但引入路径为 `behavior.skills.manager.SKILLS_DIR`（跨模块常量引用，阶段二总线化时一并整理）
- webui 零测试 → 阶段三补关键路径测试

---

## 三、用户决策记录

| 决策点 | 结论 |
|--------|------|
| 历史偏差处置 | **保持原样**，不重写已推送历史；偏差记录在案 |
| webui 总线边界 | **必须走总线**（严格），webui 不属「组装根」豁免 |
| 修复节奏 | 安全类立即修；其余全部修完再进入记忆系统开发 |

---

## 四、完整执行计划

### 阶段一：安全审查 + 修复 ✅

- 分支：`fix/webui-audit`（当前）
- 内容：见第二节「已修复」表格
- 状态：**已完成**，待提交合并

### 阶段二：总线化改造

- 分支：`refactor/webui-bus`
- 目标：webui 所有跨模块能力通过 `core.call` 获取，消灭直连 import
- 状态：**已完成**（2026-08-30），待提交合并

落地要点（与规划相比的调整）：

- 服务名最终定为：`llm.providers.*`（load/add/delete/model_add/model_delete）、
  `llm.fetch.plan/apply`、`llm.retired.list/delete`（代替规划中的
  `llm.providers.write`/`llm.fetch.run`，更贴合现有 fetch.py 函数语义）、
  `audit.recent`/`audit.summary`（代替规划中的 `audit.count`，summary 一次
  取全部聚合）、`skills.list/detail/create/save/delete`。
- **`config.toml.read/write` 未走总线**：配置页读写是 `aris.cfgtoml` /
  `get_settings` 的**基础设施直连**，按「三层三源」设计属配置系统本身，
  不视为模块间业务通讯（已记入 BUS-ARCHITECTURE.md 例外清单）。
- 注册点：`core/llm/manage.py`（新建）、`core/llm/fetch.py` 与
  `behavior/skills/manager.py`（模块级追加）、`core/bus.py`（audit 服务）。
- webui 侧：全部路由改 `core.call`；`create_app()` import 三个所有者模块
  触发注册 + `_verify_bus_services()` 启动自检（新增 `bus.has_service`）。
- 验证：`uv run pytest` 37 通过 + TestClient 全链路冒烟
  （登录/限流/7 页/技能 CRUD/穿越防护/配置穿越防护）全绿。

### 阶段三：约定过筛 + 补测试

- 分支：`chore/webui-conventions`（待建）
- 内容：
  - 全模块类型标注完整性检查（公开函数/类注解）
  - docstring 规范统一（中文 docstring）
  - 错误处理分层哲学审查：core 核心逻辑快速失败 vs 外围宽容降级
  - 补测试：auth 鉴权流程、rate_limit 限流、config 保存写回、skills CRUD 关键路径
  - 使用 `tests/support/` 现有 mock 基础设施

### 阶段四：流程防复发

- 分支：`chore/process-guardrails`（待建）
- 内容：
  - pre-commit 钩子扩展（`.githooks/pre-commit`）：
    - 禁止在 `main` 分支上提交
    - 建议在 `develop` 上非合并提交时打印警告（技术上无法完全阻止客户端行为）
  - 新增 `scripts/release-check.sh`：
    - 校验 pyproject.toml / `__init__.py` / uv.lock 版本三源一致
    - 校验当前分支为 develop 且无未合并 feature 分支
    - 输出发布检查报告
  - AGENTS.md 更新：登记 release-check 使用方式

### 阶段五：收尾验证

- 所有阶段的 feature 分支按规范（`--no-ff`）合并回 develop
- `uv run pytest` 全绿
- PROGRESS.md 记录本轮审查结论与偏差存档
- 历史保持原样不重写

---

## 五、TODO 清单

### 当前（阶段一二已完）

- [x] `fix/webui-audit` 分支提交安全修复（12 个文件）
- [x] 合并回 develop（`git merge --no-ff`）
- [x] 创建 `refactor/webui-bus` 分支
- [x] 设计总线服务接口并逐模块注册 provide()
- [x] routes 全量迁移 `core.call` + 启动自检
- [x] 阶段二 5 提交合并回 develop（`git merge --no-ff`，b85c756）

### 待办（阶段三-五）

- [x] 补类型标注 + docstring 规范化（AST 全量过筛清零）
- [x] 补 auth/rate_limit/config/skills 测试（tests/test_webui.py，11 用例）
- [x] secrets 可用性问题：补充测试时发现 providers 页缺配置 500 → 已宽容降级
- [x] pre-commit 钩子扩展（main 禁提交 / develop 直提警告，已实测三场景）
- [x] release-check.sh 脚本（版本三源 + 分支检查，发布检查报告）
- [x] AGENTS.md 登记 release-check 使用方式
- [x] PROGRESS.md 记录（2026-08-30 审查结论 + 偏差存档）
- [x] 所有分支 --no-ff 合并回 develop（一二三四阶段全部收官，48 测试全绿）

### 回归主线（阶段五之后）

- [ ] 记忆系统（PostgreSQL + pgvector）开发

---

## 六、技术决策备忘

| 决策 | 理由 |
|------|------|
| DOMPurify 静态引入（非 CDN） | 断网可用，与 marked.js 处理方式一致 |
| tomli_w 结构化写回 providers.toml | 与 fetch.py 已有写回方式一致，消除字符串拼装注入 |
| skills 目录改用包内路径 `behavior.skills.manager.SKILLS_DIR` | 与运行时 SkillManager 同源，消除 CWD 依赖 |
| AuditRecord 新增 wall_ts 字段 | 墙钟时间戳用于展示，monotonic ts 保留用于排序/算差值 |
| `_escape_toml_string` 处理控制字符 | 防止换行/制表符破坏 TOML 行结构 |
| auth 公开路径精确匹配 `/login` | 防 `/loginfoo` 等前缀伪造绕过鉴权 |
