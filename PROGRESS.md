# 开发进度

> 每次开发前先读本文件，了解最新状态。

## 当前版本：v0.3.1

## 最新状态

### 2026-09-18：store/ embedding 抽象跑通（本地 Bekko 384 维）

- 新增 `store/embedding/`：`base.py`（`EmbeddingProvider` Protocol + `EmbeddingError`）、
  `local.py`（本地 Bekko a25m，OpenVINO CPU，**懒加载** + 线程安全）、
  `__init__.py`（provider 单例注册）；`store/conf.py` + `config/store.toml`
  （provider / 模型 / batch / 截断维度）；总线服务 `store.embed`
- CLI：`aris store info`（配置 + 自检）/ `aris store embed <文本>`（打印维度与向量片段）
- 实测：`hotchpotch/bekko-embedding-v1-a25m` **384 维**编码通过；模型缓存落
  `data/models`（约 224MB）；`uv run pytest` **58 passed**
- **打包定案（取代 B/C 条目里「可选/独立环境」的口径）**：embedding 栈放
  **dependency-group `embedding`** 并加入 `[tool.uv] default-groups`——`uv sync` 一次
  装齐、`uv run` 不会把它卸掉（轻量环境用 `uv sync --no-default-groups`）
- 踩坑记录（已修）：① torch 与 torchvision 必须**同锁 PyTorch CPU 源**，否则
  torchvision 的 CUDA wheel 与 CPU torch 不匹配，报 `operator torchvision::nms does
  not exist`，`transformers` 直接导入失败；② OpenVINO 遥测往 `$HOME/intel` 写 consent
  文件，HOME 只读时会刷 warning（数据不外发，属无害噪音；已设 opt-out 环境变量，
  彻底消除需在可写 HOME 下跑一次或写 consent 文件）；③ HF 缓存经 `HF_HOME` 收进
  `data/models/`，不散落主目录
- 顺带修两处真实缺陷：① `is_running` 增 `pg_isready` 实测——崩溃后残留的
  `postmaster.pid` 会让 `pg_ctl status` **误报"运行中"**，进而 `aris db start` 拒绝
  启动（实测踩到）；② `bootstrap()` 更名 `bootstrap_env()`——函数与模块同名时被包内
  重导出遮蔽，`store.bootstrap` 拿到的是函数而非模块（已连踩两次）
- 内存实测：本地模型加载后进程峰值 RSS **约 1.2GB**，CLI 一次性命令退出即释放，
  无残留常驻（长驻服务会常驻该量级，属预期）
- 依赖新增（dependency-group）：sentence-transformers / `optimum[openvino]` / openvino /
  `transformers<5.1` / torch + torchvision（CPU）；`.venv` 约 1.5GB
- **下一步**：`store/` 的迁移机制与向量检索 helper，然后进 `knowledge/`

### 2026-09-18：store/ 环境地基跑通（`aris db` 可用）

- 新增 `store/` 模块：
  - `pgenv.py`：探针链（`ARIS_PG_BIN` → PATH 的 `pg_config` → `data/pg` → 未安装）
    + `PgEnv`（bin / pgdata / run / port / user / db）+ DSN 拼装（`ARIS_PG_DSN` 可整条覆盖）
  - `bootstrap.py`：micromamba（固定版本 + sha256 校验）→ conda-forge 装 postgresql +
    pgvector → `initdb`（UTF8、trust、仅监听 127.0.0.1）→ 启停 → 建库 →
    `CREATE EXTENSION vector` → 写 `data/pg/versions.txt`；全流程幂等
  - `db.py`：psycopg 连接与探活；对外总线服务 `store.health`
- CLI：`aris db init|start|stop|status|psql`（psql 后续参数原样透传）
- 实测：**PostgreSQL 17.11 + pgvector 0.8.1**；`data/pg` 约 166MB，另有包缓存
  `data/pg-pkgs` 约 91MB（可随时删）；首次下载实测约 **40MB**（原估 300MB 偏保守）；
  `uv run pytest` **51 passed**
- 踩坑记录（已修）：① `pg_ctl -o "-k <相对路径>"` 必然失败——postgres 启动后会
  chdir 到数据目录，故 `PgEnv` 内路径统一转绝对路径；② conda 默认把包缓存、元数据与
  `~/.conda/environments.txt` 写到主目录，已用 `MAMBA_ROOT_PREFIX` / `CONDA_PKGS_DIRS`
  / `XDG_CACHE_HOME` / `HOME` 全部收进 `data/`；③ `pg_ctl` 失败信息太少，已在
  `bootstrap.start()` 附带服务日志末尾
- 新增依赖 `psycopg[binary]`；文档同步（KNOWLEDGE-BASE 第 3.3 节改为 Python 实现并记录
  实测版本；AGENTS 模块划分 / 现状）
- **下一步**：`store/` 的 embedding 抽象（本地 Bekko，模型落 `data/models/`）、迁移机制
  与向量检索 helper

### 2026-09-18：议题 B（摄入侧）/ C（存储切分）定案 —— 知识库方案收尾

- **B 摄入侧**：来源 = 本地文件/目录 + HTML（`trafilatura` 已是既有依赖）；**不做**
  PDF、目录监听、从对话自动沉淀。**CLI 先行**（`aris knowledge add|list|remove|search`），
  WebUI 上传排第二；**agent 不给摄入权限**（只给检索，与「用户投喂资料」定位一致）。
  增量 = **content hash 幂等 + 软删重建**，两表 `knowledge_docs` / `knowledge_chunks`。
- **C 存储与切分**：**向量维度 384（本地 Bekko）**，不用云端——云端是 `memory/` 冷侧
  的事，且可避免 Cloudflare 断联降级逻辑。本地 embedding 属重依赖 → 可选/独立环境安装
  + `store/` 懒加载，未安装则知识库自动禁用；摄入串行限并发（压测下约 1164% CPU，
  避免打满主机）。分块 = 标题层级切 + 定长兜底重叠（保留 `heading_path`）；元数据
  11 字段 + `meta jsonb`；索引 HNSW + cosine（`m=16` / `ef_construction=64`），
  先导数据后建索引。
- **实现次序**：**`store/` 底层先行** → `knowledge/` → `memory/` 复用同一底层。
- **总线定名**：按职责核对 `core/bus.py`——含服务注册表（`provide`/`call`）+ 事件广播
  （`subscribe`/`emit`）+ 审计查询，故定名**「跨模块通讯总线」（CMCB）**；**暂不改名**
  （涉及既有 16 个服务命名与多处文档），留作待办。
- 知识库四个议题（A/B/C/D）**全部定案**；已同步 `AGENTS.md` 与
  `developDoc/KNOWLEDGE-BASE.md`（第 4、5 节）。本轮仅文档，未写代码。
- **下一步**：进入实现——先做 `store/`（PG 环境 bootstrap → 连接池 → 迁移 →
  embedding provider → 建表 helper）。

### 2026-09-18：议题 A（边界归属）/ D（检索侧）定案

- **A 边界与归属**：新建两个顶层模块——
  - `store/`：embedding 抽象（文本 → 向量）+ PostgreSQL/pgvector 基础设施
    （DSN、连接池、迁移、向量检索 helper），**不认识** `memory/` / `knowledge/`
  - `knowledge/`：知识库业务（摄入、分块、来源管理、检索语义）
  - 依赖单向 `knowledge →（大总线）→ store`；`memory/` 后续复用 `store/`
  - **模型本体放 `data/models/`**，不进仓库
- **A3 不做 skill**：知识库属**内部底层设施**，能力经大总线暴露；skill 是外部扩展
  接口，内部模块绕经它只增一层壳与延迟。启用开关 `config/knowledge.toml: enabled`。
- **D 检索侧**：agent 工具**自主调用**（与 `web_search` 并列，不做每轮自动注入）；
  第一阶段**纯向量**（混合检索 / rerank 列第二阶段）；结果格式沿用 web_search 约定
  且**必带来源标识**（路径 + 标题 + 位置）；与记忆检索**两条独立通路**，不合并入口。
- 总线服务（实施时落表）：`store.embed` / `store.health` / `store.migrate` /
  `knowledge.search` / `knowledge.ingest` / `knowledge.sources`。
- **新增待定**：用户计划给总线重新取名，届时统一调整既有 16 个服务命名。
- 已同步 `AGENTS.md`（模块划分 / 已定案 / 待定 / 开发路线）；详
  `developDoc/KNOWLEDGE-BASE.md` 第 4 节。本轮仅文档。
- **下一步**：议题 B（摄入侧）/ C（存储切分）。

### 2026-09-18：数据库部署方案定案（前置阻塞解除）

- **结论**：数据库环境**不依赖系统安装**，由项目脚本按需自动获取便携实例，
  目标「clone 下来就能用」。定案 **micromamba + conda-forge**（`postgresql` +
  `pgvector` 同源，免 root、免编译、装到 `data/pg/`，`.gitignore` 已覆盖）。
- 排除 EDB 官方 binaries tarball（实测 403，改走许可跳转，且不含 pgvector），
  也排除二进制入仓（体积 200MB+，违反「数据不进 git」）。
- 探针链：`ARIS_PG_BIN` → PATH 中 `pg_config`/`postgres` → `data/pg/` → 下载。
  代码只认 DSN，不感知实例来源 → 该决策不影响议题 A/B/C/D。
- **pgvector 取预编译包、不源码编译**：读源码确认 pgvector 在 glibc Linux 上自动启用
  `USE_TARGET_CLONES`（运行期选 FMA 快路径）；本机 Xeon E5-2673 v3 无 AVX-512，
  `-march=native` 无额外收益。
- 已同步 `AGENTS.md`「已定案」；详 `developDoc/KNOWLEDGE-BASE.md` 第 3 节。
- 未写代码，仅文档；下一步进议题 A（边界与归属）/ D（检索侧接口）。

### 2026-09-14：知识库进入准备阶段（商讨中，未定案）

- 用户决定启动**知识库**能力建设，定位为**面向外部资料的独立 RAG 知识检索
  能力**，与 Aris 个人记忆分开。
- 已开分支 `feat/knowledge-base`（从 `develop` @ `7f0b4dd` 拉取）。
- 新建 `developDoc/KNOWLEDGE-BASE.md`（**商讨稿**）：登记定位、可沿用的既有
  地基、前置阻塞、待商讨决策点（A 边界归属 / B 摄入侧 / C 存储切分 / D 检索侧）。
- **尚未定案**：知识库与 `memory/`（记忆系统主线）的边界与先后次序均待商讨；
  本轮只做准备，未写代码。
- **前置阻塞（实机探测）**：本机 PostgreSQL / pgvector / docker / podman 均不存在，
  数据库环境搭建方式待定。

### 2026-08-30：版本 v0.3.1（WebUI 安全审查 + 总线化改造 + 防复发机制收官）

- 版本号三源同步 bump 至 **v0.3.1**（patch 级：本轮为修复/重构/工具，无新功能）。
- 全部阶段合并回 develop，`uv run pytest` 48 通过，`scripts/release-check.sh` PASS。
- 详细条目见下方「2026-08-30：WebUI 安全审查 + 总线化改造 + 防复发机制」。

> 遗留待办（2026-08-23 记）：仪表盘系统状态区域、htmx（可选）、Lucide 图标（可选）。

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
9. 知识库（独立 RAG 知识检索）—— **方案已定案（2026-09-18，A/B/C/D）**，
   实现次序 `store/` 底层先行；详见 `developDoc/KNOWLEDGE-BASE.md`

## 当前聚焦

**知识库实现启动**（方案已全部定案，2026-09-18）与**记忆系统**（PostgreSQL + pgvector）
- 知识库：`developDoc/KNOWLEDGE-BASE.md`（A/B/C/D 全定案），分支 `feat/knowledge-base`；
  **进行中 = `store/` 模块**：环境地基（探针 / bootstrap / 连接探活 / `aris db`）与
  embedding 抽象（本地 Bekko 384 维 / `aris store`）已跑通，下一步做迁移机制与向量
  检索 helper，然后才动 `knowledge/`
- 记忆系统：主线未取消，`memory/` 仍为占位；后续**复用 `store/`**（不自建第二套）
- 数据库环境：部署方式已定案（micromamba + conda-forge 便携实例，脚本自动获取，
  见 `developDoc/KNOWLEDGE-BASE.md` 第 3 节）
- 待办：总线改名（已定名 CMCB，涉及面大暂缓）
- WebUI 管理后台已完成（v0.3.0，2026-08-23）
