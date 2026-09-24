# 开发进度

> 每次开发前先读本文件，了解**当前**状态。
> 本文件只记当前进度（现状速览 / 最近动态 / 当前聚焦 / 路线）；已翻页的历史条目
> 原文归档在 `developDoc/PROGRESS-ARCHIVE.md`（含各次踩坑记录，查旧事去那里）。

## 当前版本：v0.4.2（beta，2026-09-24）

## 现状速览

| 模块 | 状态 |
|---|---|
| `core/` | 完成：CMCB 总线（43 个服务，含事件广播 + 审计）+ LLM 多提供方 / fallback / 流式 / 工具调用 |
| `behavior/` | 完成：agent loop、工具注册表、内置工具（`web_search` / `web_open` / `knowledge_search`）、skills 系统 |
| `chat/` | 完成：会话逻辑 + TUI（`aris chat`），定位开发调试 |
| `persona/` | 提示词工程版（单一 `persona.system_prompt`）；多人格见 BACKLOG #4 |
| `webui/` | 完成：鉴权 / 仪表盘 / 审计 / 提供商 / 技能 / 配置 / 日志 / 知识库页 |
| `serve/` | **完成（v0.4.1）**：`aris serve` 一条命令起全套（缺则自建 PG、自启、预热 embedding、并入 WebUI），`--only/--skip/--dry-run` 可裁剪 |
| `store/` | 完成：便携 PG 17.11 + pgvector 0.8.1、embedding（本地 Bekko 384 维）、迁移 + 向量 helper |
| `knowledge/` | 首期完成：两表 / 分块 / 摄入 / 纯向量检索 / CLI / agent 工具 / WebUI 页 |
| `memory/` | **占位**，复用 `store/`（BACKLOG #5） |
| `voice/` | **占位**（选型见 `developDoc/stt&&tts选型.md`） |

- **入口**：`aris serve` 一条命令即可（首次自动获取便携 PG，需联网数分钟）；
  `aris doctor` 体检、`aris chat` 终端对话（调试用，与应用互不干涉）
- 测试：`uv run pytest` **103 passed**（DB 未运行则集成用例自动 skip）
- 数据库：便携实例在 `data/pg`，项目本地、不注册系统服务；`aris serve` 会按需自建/自启，
  退出时只停自己拉起的那个
- 知识库现有资料：`data/knowledge/刑法.md`（约 129 块）
- 待办方向：`developDoc/BACKLOG.md`（7 条中长期）
- 已知陷阱（踩坑档案，修完就补）：`AGENTS.md`「已知陷阱」节

## 最近动态

### 2026-09-24：v0.4.2 发布（首个带 beta 标记的版本）

- **为什么是 v0.4.2 而不是 v0.4.5**：serve 是「clone 下来一条命令起服务」的体验入口，
  本打算攒到 v0.4.5；但 memory / persona 从开发到完善可能吃掉好几个版本号、把 v1.0
  提前，于是 serve 收在 v0.4.1，把 v0.4.2 留给**真实走一遍新的版本机制**
  （上一轮只是 0.4.1 → 0.4.2 → 回滚的演练，不算真发布）
- **本版内容** = v0.4.1 的全部能力（serve 一条命令起服务）+ 版本机制与发布规范落地：
  - 版本号改成单一来源（`src/aris/__init__.py`）：pyproject 走 dynamic、uv.lock 不再
    记录本项目版本。**bump 实测只改了 `src/aris/__init__.py` 一个文件**，uv.lock 零变更
  - **beta 标记规范**：0.x 全段为 beta（正式版留 v1.0.0），tag 带 `-beta` →
    `v0.4.2-beta`；v1.0.0 起正式版 `vX.Y.Z`、预发布 `vX.Y.Z-beta.N` 且 `__version__`
    同步写 `1.3.0b1` 形式。规则收在 `scripts/lib-version.sh`，两个脚本共用
  - README 标题下加发布公告（隆重发布 v0.4.2 + 一句话功能概述）
- **发布流程**：`bump-version.sh 0.4.2` → `release-check.sh` **PASS** →
  合并 `main` → tag `v0.4.2-beta`
- 测试：`uv run pytest` **103 passed, 10 skipped**

### 2026-09-24：版本号改为单一来源（第三条开发规范）

- 背景：版本号原先在 `pyproject.toml` / `src/aris/__init__.py` / `uv.lock` **三处各写
  一遍**，0.2.0 / 0.2.2 / 0.2.6 每个版本都要额外的「同步 uv.lock / `__version__`」提交，
  v0.4.1 还误把版本行混进了功能提交。回望全部提交后定案——**检查脚本只能治症状，
  改成结构上只剩一处**
- **唯一源 = `src/aris/__init__.py` 的 `__version__`**：`pyproject.toml` 改
  `dynamic = ["version"]` + `[tool.setuptools.dynamic] version =
  {attr = "aris.__version__"}`；**`uv.lock` 不再记录本项目版本**（实测 `uv lock` 把
  `version = "0.4.1"` 那行删掉了），于是「三源同步」这个动作本身消失，也不再有同步提交
- **两个实测踩坑（已进 AGENTS「已知陷阱」）**：① uv 默认只按 `pyproject.toml` 判定
  元数据缓存，改了 `__init__.py` 也不重建（实测 `uv sync` 后仍是旧版本）→ 必须加
  `[tool.uv] cache-keys = [{ file = "src/aris/__init__.py" }]`；② 版本号必须能被
  setuptools 解析为 PEP 440（`9.9.9-test` 直接 `InvalidVersion` 构建失败）
- 新增 `scripts/bump-version.sh <版本|patch|minor|major>`：校验干净 develop / 版本合法 /
  tag 未占用 → 改源 + `uv lock` + `uv sync` → 打印提交与发布命令（**只改文件不提交**）
- `scripts/release-check.sh` 重写为六项：单一来源结构（pyproject 不得再有静态 version、
  必须有 dynamic + attr + cache-keys）、已安装元数据一致、`uv lock --check`、分支为
  develop、无未合并分支、目标 tag 未占用；各失败分支已逐条实测
- `AGENTS.md`：「Git 开发流程」里两条过时描述改掉，新增**「版本号更新（2026-09-24
  定案）」**小节，「已知陷阱」新增「打包 / 版本」分组
- 验证：`aris --version` → `Aris 0.4.1`；release-check 在 feature 分支如实报
  FAIL（分支 + tag），在 develop 上结构项全绿
- **本次不改版本号**：只改机制，版本仍为 v0.4.1

### 2026-09-19：serve 收尾（v0.4.1 —— 首个「clone 下来一条命令起服务」的版本）

- **缺则自建**：`store.start(init_if_missing=...)`——便携实例不存在时直接
  `bootstrap_env()`（micromamba + conda-forge，联网首次数分钟），用户不必先敲
  `aris db init`；开关 `config/serve.toml: init_db`（默认开），探针相应报
  「未初始化（启动时将自动获取）」
- **退出语义定案并落地**（SERVE.md 新增小节）：`0` 正常（含 Ctrl-C 正常收尾）、
  `1` required 失败或 WebUI 起不来、`2` 参数写错、`130` 收尾期间再次 Ctrl-C 强制退出
  （日志提示库可能仍在跑、用 `aris db stop`）
- **README 快速开始改为 `aris serve` 一条命令**，补调试选项与 CLI 表
  （serve / doctor / web / db / knowledge）
- **端到端实测**（真实 `aris serve`，无参数）：PG 自启 → embedding 后台预热 →
  `/` 与 `/knowledge` 均 200 → SIGINT → uvicorn 优雅关闭 → 停掉自己拉起的库 →
  **退出码 0**，库回到停止态
- 测试 `uv run pytest` **103 passed, 10 skipped**（新增「缺则自建」探针分支用例）

### 2026-09-19：serve 收尾——组装根上收 + doctor 合流探针（SERVE.md 第 4–5 步）

- **唯一组装根**：`serve.assemble()` 成为唯一一份「import 哪些所有者模块」的清单；
  `webui.create_app()` 只搭 HTTP 层（原先它自己 import `llm.fetch`/`llm.manage`/
  `skills` 并调 `_verify_bus_services()`，与 `cli.py` 那套重复、必然漂移）；
  测试改在 `tests/conftest.py` 调 `assemble()`（测试也是宿主）
- **依赖清单仍归各模块自己声明**：`webui._REQUIRED_SERVICES` → 公开的
  `webui.REQUIRED_SERVICES`，由新增的 `services` 步骤（required）统一核验——原实现
  只有 WebUI 那条路径会被检查
- **`aris doctor` 合流**：环境自检（Python / C 扩展 / .env / 数据目录）+
  `serve.probe_all()`，与 `aris serve --dry-run` 走同一条探针路径；LLM 体检收敛为
  总线服务 `llm.providers.check`（`aris llm check`、doctor、serve 探针共用一份结论，
  原先判断散在 CLI 里）
- 顺带：serve 的 `core.llm` 探针现在会把体检错误直接报出来（`✗` + 首个错误 +
  `aris llm check` 提示），不再只数提供方个数
- 实测：`aris doctor` 八项探针全绿并给出可操作结论；`aris serve --dry-run` 8 步；
  `aris web` 起服务 GET `/` → 200，第二个实例被端口探测拒绝（exit 1，错误文案明确）；
  `uv run pytest` **102 passed, 10 skipped**
- 剩余缺口（SERVE.md §10）：工具注册表 / agent loop / LLM engine 仍是会话级对象，
  等 #4/#7 时由 serve 上收；退出细节（二次 Ctrl-C、退出码明细）待定

### 2026-09-19：serve 首期实现（`aris serve` 可用）

- 新增 `src/aris/serve/{__init__,conf,steps}.py`：组装根 `assemble()`（集中 import 触发
  注册）、步骤表（探针 + 启动动作）、编排（`--only` 依赖闭包 / `--skip` 硬排除 /
  失败分级 / 启动清单 / 收尾）；新增 `config/serve.toml`
- 各模块补启动 hook：`store.start|stop|db_status|embed_preload|embed_status`
  （含 `LocalBekkoProvider.warmup()`）、`knowledge.start`、`webui.probe|start`
  （`port_in_use()` 端口探测，`aris web` 也走同一道）；`core.bus.services()` 列出
  已注册服务
- CLI：`aris serve [--only a,b] [--skip c] [--dry-run]`；并把 `serve` / `web` 的控制台
  日志级别固定 INFO——**启动清单被 WARNING 阈值吞掉就等于没有**
- 实测：`--dry-run` 七步探针全绿（PG 未运行时 knowledge 报「待数据库启动后建表」而非红）；
  真实 `aris serve --skip webui`：PG 自启（顺带清残留 pidfile）→ 迁移 → embedding 后台
  预热 → knowledge 1 文档/129 块 → 退出时停掉自己拉起的库；无阻塞步骤时不执行收尾
  （否则「起了又立刻停」，`--only store.db` 这种用法会彻底没用）
- 测试：`tests/test_serve.py` 9 例；`uv run pytest` **102 passed, 10 skipped**
- 待做（SERVE.md 第 4–5 步）：上收 `webui` 的 import 与 `_REQUIRED_SERVICES`、与
  `aris doctor` 合流探针；工具注册表 / loop / LLM engine 仍是会话级对象（#4/#7 时上收）

### 2026-09-19：serve 模块方案定案（启动编排，`developDoc/SERVE.md`）

- 定位：`aris serve` = **组装根 + 启动编排（相当于 init）**——把各模块按序拉起、前台
  打印启动清单与日志、`Ctrl-C` 收尾；**单向**（只调别人的启动动作，**不对外提供查询
  服务**）、**非守护**、**不含 TUI**
- 定案要点：
  - **PG 没跑就自启**；退出时**只停「自己拉起的」那个**（启动前探活为假才算自己起的）
  - **embedding 启动即后台预热**（+ 就绪标志）——懒加载会让首个工具调用顶穿 timeout
  - **WebUI 默认并入**；端口被占则**拒绝启动 webui 并提示**，其余模块照常，不整体退出；
    `aris web` 保留并加同一道端口探测
  - **失败分级**：required 仅 `store.db`，其余 optional；降级/跳过/拒绝**一律记日志**
    并给可执行提示（严禁静默降级）
  - **调试选项** `--only` / `--skip` / `--dry-run` + `config/serve.toml`（CLI 覆盖配置）
- 顺带收口：`cli.py` 与 `webui/__init__.py` 里重复的 import 与 `_REQUIRED_SERVICES`
  自检**上收到 serve**（现在两处各一套，已存漂移风险）；`aris doctor` 与 serve
  共用探针；WebUI 仪表盘「系统状态区域」直接读各模块服务，不经过 serve
- 新增 `developDoc/SERVE.md`（定位/三类服务/启动顺序/自启策略/失败分级/配置/接缝/
  实现次序）；`AGENTS.md` 模块划分与文档索引同步
- 商讨补充定案：**`aris chat` 是纯前端，与 serve 互不干涉**（既不自启也不被自启，
  不触发 PG 自启与预热）；**人格与对话历史的载体先置着**（`data/personas/` 文件 vs
  PG 表、会话是否落 PG —— 做 #4/#5 前必须先定，记入 BACKLOG #4 与 AGENTS 待定）
- **下一步：按 SERVE.md 第 10 节开始实现 serve**；真 API 实测等用户找低成本方案
- 未写代码，实现次序见文档第 10 节

### 2026-09-19：精简 PROGRESS.md + `.workbuddy/` 进 gitignore

- `PROGRESS.md` 只留当前进度（现状速览 / 最近动态 / 当前聚焦 / 路线），历史条目
  原文移至 `developDoc/PROGRESS-ARCHIVE.md`；此后只在顶部追加、阶段性搬运
- `.gitignore` 补 `.workbuddy/`（本地工具目录，不入库）
- 踩坑记录分层：**会重复咬人的一行进 `AGENTS.md`「已知陷阱」**（每个会话自动读到），
  长篇叙述留在当轮条目、过时随归档下沉
- 纯文档改动，未提交

### 2026-09-19：建立后续待办清单（`developDoc/BACKLOG.md`）

- 7 条中长期方向落 `developDoc/BACKLOG.md`：① 提供商与 LLM 协议更新优化
  ② Skills 迁到 `data/skills/` ③ 开放各模块对外接口（插件系统底座）④ 多人格并行
  ⑤ 上下文压缩（属记忆系统）⑥ 多模态支持 ⑦ 自动任务与主动操作
- 依赖速查：#3 是 #4/#7 的底座；`store/` 已就位 → #5 可开工；#2 独立可插队
- `AGENTS.md` 文档索引加一行指向本文件

### 2026-09-19：总线文档与注释统一改名 CMCB

- 定名「跨模块通讯总线」（CMCB）落到**称谓层**：架构文档 `BUS-ARCHITECTURE.md`
  → `CMCB.md`（git mv 保留历史），`AGENTS.md` / `README.md` 与 src 五个文件的
  注释 / docstring 同步；**代码标识符（`core/bus.py`、函数名、服务名）保持不变**
- 验证：`uv run pytest` 93 passed, 10 skipped；合并 `docs/cmcb-rename` → `develop`

### 2026-09-18：v0.4.0 发布（知识库首期）

- 三源 bump v0.4.0 → 合并回 `main` → 打 tag `v0.4.0`；本版 = `store/` 地基 +
  `knowledge/` 首期 + agent 工具 `knowledge_search` + WebUI 页 `/knowledge`
  （同版带来免鉴权模式：未配密码时只绑回环）
- 同版修三个真 bug：WebUI 上传后无限刷新、`is_running` 误判、残留 pidfile 挡启动
  （细节见归档）

## 当前聚焦

知识库首期已随 v0.4.0 发布，下一步候选（尚未拍定）：

1. **serve 收尾**——SERVE.md 第 4–5 步：上收 `webui` 的 import 与 `_REQUIRED_SERVICES`
   （纳入 serve 组装根）、与 `aris doctor` 合流探针
2. **真 API 实测**——对投喂过的资料提问，看 Aris 是否自主调用 `knowledge_search`、
   来源与距离是否合理（此前验证均为 mock；等用户找低成本方案）
3. **知识库第二阶段**——PDF 摄入 + 混合检索（含中文 FTS）
4. **记忆系统**——`memory/` 复用 `store/`（上下文压缩在此落地；动手前须先定
   人格/会话的持久化载体，见 AGENTS「待定」）
5. 低优先级遗留：WebUI 仪表盘系统状态区域（读各模块服务，不经 serve）、
   htmx（可选）、Lucide 图标（可选）

## 开发路线

1. ✅ 项目骨架（2026-08）
2. ✅ 接入 LLM（2026-08-09）
3. ✅ 跑通文字对话（2026-08-09）
4. ⬜ 记忆系统（PostgreSQL + pgvector）—— **主线下一步**，`memory/` 复用 `store/`
5. ✅ 人格系统（提示词工程起步，2026-08-12）；世界观 / 人际关系 / 成长轨迹待演进
6. ⬜ 语音链路（STT → LLM → TTS）
7. ✅ 行为扩展：函数调用（2026-08-09）、联网搜索（2026-08-09）、skills（2026-08-12）；
   MCP 待后续
8. ⬜ GraphRAG
9. ✅ 知识库首期（v0.4.0）；第二阶段 PDF + 混合检索待做，详见 `developDoc/KNOWLEDGE-BASE.md`
