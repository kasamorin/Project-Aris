# 知识库（Knowledge Base）—— 商讨稿

> **状态：商讨中，未定案。本文件是待商讨的议题清单，不是设计结论。**
> 讨论出结论前**不要照此实现**。结论落定后请把对应小节改写为「定案」，
> 并在 `AGENTS.md` 的「已定案」中登记一句摘要。

- 起始日期：2026-09-14
- 开发分支：`feat/knowledge-base`（从 `develop` @ `7f0b4dd` 拉取）
- 阶段：**全部议题已定案**（A/B/C/D，2026-09-18），尚未写代码；实现次序：`store/` 底层先行

---

## 1. 背景与定位

2026-09-14 用户提出要为 Aris 做「知识库」。经确认，其定位是：

> **面向外部资料的独立 RAG 知识检索能力** —— 与 Aris 的**个人记忆分开**，
> 走 embedding + 向量检索，用于让 Aris 检索并引用用户投喂的资料。

这与两处既有记录相关但**都不等同**，商讨时需明确对齐：

| 既有记录 | 关系 |
|---|---|
| `SKILLS.md` 演进待办「知识库做成独立 skill」 | 旧定位是 skill 形态；知识库需要**常驻检索服务**，如何结合待定（议题 A3） |
| 开发路线第 4 项 **记忆系统**（`memory/`） | 知识库是**独立模块 `knowledge/`**，底层向量与数据库设施由新建 `store/` 共享（A1 已定案，见 4.1） |

**注意**：知识库的出现**不取消记忆系统主线**，两者先后次序与关系尚未商讨决定。

---

## 2. 可沿用的既有地基（已定案，不重新讨论）

以下来自 `AGENTS.md` 与 `developDoc/EMBEDDING.md`，直接沿用：

- **Embedding 双 provider**：热记忆本地 Bekko-embedding-v1-a25m（384 维，
  OpenVINO CPU）/ 冷记忆云端 Cloudflare BGE-M3（1024 维），**维度不同不混表**，
  各建独立 pgvector 表
- **存储**：PostgreSQL + pgvector；**向量检索由数据库执行**，与 provider 无关
- **实现方式**：走 RAG，但**不用现有框架**（LangChain / LlamaIndex 等），自研轻量实现
- **表结构预留宽松**，为后续 GraphRAG 留口
- **重依赖隔离**：sentence-transformers / openvino 等放 `pyproject.toml` 的
  dependency-group `embedding`（默认安装、代码侧懒加载；轻量环境可
  `uv sync --no-default-groups`）
- **模块间通讯走 `core.call` / `core.provide`**，服务命名 `module.service`
- 密钥一律放 `.env`；文档中禁止写死密钥

---

## 3. 数据库环境部署方案（2026-09-18 定案）

**问题**（2026-09-14 实机探测）：`psql` / `pg_config` / `pgvector` / `postgresql`
服务均不存在，`docker` / `podman` 也没有。而"要求用户先 `pacman -S postgresql`"
与项目既有规范（clone 下来就能用）相冲突。

**定案目标**：**不依赖系统安装**，由项目脚本按需自动获取便携实例；系统已装则直接用。

### 3.1 探针链（按序命中即终止）

1. `ARIS_PG_BIN` 环境变量（显式覆盖，指向外部安装）
2. PATH 中的 `pg_config` / `postgres`（系统已装则直接用）
3. 项目内 `data/pg/bin/postgres`（脚本此前自动装的）
4. 全无 → 自动下载（见 3.2）

### 3.2 获取方式：micromamba + conda-forge（定案）

实测排除 **EDB 官方 binaries tarball**：`get.enterprisedb.com/postgresql/
postgresql-*-linux-x64-binaries.tar.gz` 现返回 **403**（改走 `getfile.jsp`
许可跳转），无法脚本化，且本身不含 pgvector。

定案改用 **conda-forge**：

- `postgresql` 与 `pgvector` **同源**，版本匹配由 solver 保证（conda-forge 上
  `pgvector` 有 linux-64 / linux-aarch64）
- **实测取到 PostgreSQL 17.11 + pgvector 0.8.1**：`pgvector=0.8.6` 与
  `postgresql=17` 依赖冲突（libpq 17.0 钳制），故规格写 `pgvector>=0.8`、
  **不锁补丁版本**，由 solver 决定；日后要用 0.8.6+ 需换 PG 大版本或源码编译
- 由 **micromamba 单文件静态二进制**驱动，**免 root、免编译**，安装到 `data/pg/`
  （`.gitignore` 已覆盖 `data/`，仓库零体积增长）
- 首次下载实测约 **40MB**（29 个包；原先估的 300MB 偏保守）——走单一路径，
  不保留"系统 pacman 优先"的双路径分支

**pgvector 直接取 conda-forge 预编译包，不源码编译。** 依据（已读源码确认）：
pgvector 在 glibc Linux + GCC/Clang 上会自动启用 `USE_TARGET_CLONES`
（`src/halfvec.h`），生成 `target_clones("default", "fma")`，**运行期按 CPU 选 FMA
快路径**，通用编译的包同样吃到 SIMD。而本机 CPU 为 Xeon E5-2673 v3（Haswell-EP），
**无 AVX-512**，`-march=native` 相比 `target_clones` 无额外收益。

> 可选后手（当前不需要）：若日后换到支持 AVX-512 的 CPU，可用该 PG 的 `pg_config`
> 源码编译 `make OPTFLAGS="-march=native"` 覆盖，收益量级约 10~20%。

### 3.3 实现形态与职责（幂等）

**实现落点在 `store/` 模块（Python），不另写 shell 脚本**——原先设想的
`scripts/pg-bootstrap.sh` / `pg-ctl.sh` **取消**：探测与生命周期统一在 Python 编排
（`subprocess` 调 `initdb` / `pg_ctl` / `psql`），避免 shell 与 Python 两套探测逻辑
日后各自漂移。

| 文件 | 职责 |
|---|---|
| `store/pgenv.py` | 探针链 + `PgEnv`（bin / pgdata / run / port / user / db）+ DSN 拼装 |
| `store/bootstrap.py` | micromamba 获取（sha256 校验）→ conda 环境 → `initdb` → 启停 → 建库 → 建扩展 → `versions.txt` |
| `store/db.py` | psycopg 连接与探活（对外总线服务 `store.health`） |
| `store/conf.py` + `config/store.toml` | embedding 可调参数（provider / 模型 / batch / 截断维度） |
| `store/embedding/` | embedding 抽象（Protocol）+ 本地 Bekko provider（懒加载；总线服务 `store.embed`） |

- CLI：`aris db init|start|stop|status|psql`（`psql` 的后续参数原样透传）
- 服务端口默认 **55432**，避开将来系统 PG 的 5432；socket 落 `data/pg/run`，
  仅监听 `127.0.0.1`
- micromamba **固定版本 + sha256 常量写死** `bootstrap.py`（升级时两处一起人工更新）
- Python 侧依赖 `psycopg[binary]`（自带 libpq，不依赖系统 libpq）
- **系统已装则不下载**（`ARIS_PG_BIN` / `pg_config` 命中）：只确保库与扩展存在

**实现状态（2026-09-18 跑通）**：

- **数据库**：`aris db init|start|stop|status|psql` 全部可用；实测 PostgreSQL **17.11** +
  pgvector **0.8.1**（`data/pg` 约 166MB，另有包缓存 `data/pg-pkgs` 约 91MB 可随时删）。
  micromamba 与 conda 的根前缀、包缓存、元数据缓存以及 `HOME` 全部收在 `data/` 下，
  不污染用户主目录；`pg_ctl` 启动失败时会附带服务日志末尾，便于定位。
- **embedding**：`aris store info|embed` 可用；实测本地 Bekko a25m **384 维**编码通过，
  模型缓存落 `data/models`（约 224MB）。
- **重依赖打包（2026-09-18 定案）**：embedding 栈（sentence-transformers /
  `optimum[openvino]` / openvino / `transformers<5.1` / torch + torchvision）放
  **dependency-group `embedding` 并加入 `[tool.uv] default-groups`**：`uv sync` 一次装齐
  （要轻量环境用 `--no-default-groups`），同时避开「`uv run` 隐式把额外依赖卸掉」的坑。
  **torch 与 torchvision 必须同锁 PyTorch CPU 源**（`[tool.uv.sources]` + explicit index）：
  两者不同源会报 `operator torchvision::nms does not exist`，进而 `transformers` 导入
  失败（实测踩到）。

### 3.4 边界

- **代码只认 DSN**，不感知是系统实例还是便携实例 → 本决策**不影响议题 A/B/C/D**
- WebUI 的「psql 未安装」提示保留，但降级为**兜底**：正常路径是引导用户执行
  `aris db init`

---

## 4. 已定案：A 边界与归属 / D 检索侧（2026-09-18）

### 4.1 A. 边界与归属

**A1 —— 新建两个顶层模块，共享基础设施：**

| 模块 | 职责 | 边界 |
|---|---|---|
| `store/` | embedding 抽象（文本 → 向量，Protocol + 多实现）+ PostgreSQL/pgvector 基础设施（DSN、连接池、迁移、向量检索 SQL helper） | **不认识** `knowledge/` / `memory/`，不做业务语义 |
| `knowledge/` | 知识库业务：摄入、分块、来源管理、检索语义 | 经总线使用 `store/`，不直连 psycopg |

- `memory/` 后续实现时**复用 `store/`**，不自建第二套连接/迁移/embedding。
- **模型本体（Bekko 等）放 `data/models/`**，不进仓库（与「数据不进 git」一致）。
- 依赖方向：`knowledge →（总线）→ store`；底层永不反向依赖业务模块。

**A2 —— 存储实现细节归 `store/`**：热/冷两套 provider、维度差异（384/1024）、
多表并存等既有定案（见 `EMBEDDING.md`）全部落在 `store/` 内部，业务模块只感知
「向量维度」与「表名」这类契约。

**A3 —— 不做 skill。** 知识库属**内部底层设施**，能力经**大总线**暴露；
skill 是**外部扩展接口**，内部模块绕经 skill 只增一层壳与延迟。

**启用开关**：`config/knowledge.toml` 的 `enabled`（模块级可调参数，走既有
`cfgtoml` 加载器；缺文件/缺键静默用默认）。

**总线服务（实施时落表）**：
- `store.embed` —— 文本 → 向量（按 provider 参数化）
- `store.health` / `store.migrate` —— 连接健康与 schema 迁移
- `knowledge.search` / `knowledge.ingest` / `knowledge.sources`

> **总线改名待办（2026-09-18 用户提出）**：用户计划给总线重新取名，届时统一
> 调整命名（含既有 16 个服务）。本轮不动。

### 4.2 D. 检索侧

- **D1 —— agent 工具自主调用**：暴露 `knowledge_search` 工具，与 `web_search`
  并列，由 Aris 自己判断何时查；**不做每轮自动 RAG 注入**（阈值误判会污染上下文
  且难调试）。后手：若实测 Aris 不主动查，再评估「system prompt 里列知识库目录」
  这类低成本提示（类似 skills 菜单），**不改 `knowledge/` 模块**。
- **D2 —— 第一阶段纯向量检索**（pgvector ANN），零新依赖。混合检索（向量 +
  全文）与 rerank 均列第二阶段。**注意**：PG 无内置中文分词，混合检索要先解决
  分词（`zhparser`/`pg_jieba` 需编译进 PG，`pg_trgm` 为退路），此事第二阶段单独定。
- **D3 —— 结果格式沿用 `web_search` 约定**：外层 JSON
  `{"type": "knowledge_search_results", "results": [...]}` + 内部 markdown 省 token，
  每条带自增 id；**必须带来源标识**（文件路径 + 标题 + 位置/序号）——可引用是
  知识库的存在意义。
- **D4 —— 与记忆检索保持两条独立通路**，契约形态对齐，**不合并统一入口**：
  记忆 = 自身所知，知识 = 外部资料需引用，信任级别不同，合并会让 Aris 分不清
  来源、也让调试变难。将来若要合并，因契约一致属纯加法。

---

## 5. 已定案：B 摄入侧 / C 存储与切分（2026-09-18）

### 5.1 B. 摄入侧

- **B1 数据来源**：**本地文件/目录投喂**起步，顺带 **HTML / 网页存档**（`trafilatura`
  已是既有依赖，成本低）。**不做**：目录监听（`watchdog` 常驻 + 新依赖，牵入后台进程
  概念）、PDF（重依赖 + 表格/扫描件解析质量参差）、从对话自动沉淀（与「用户投喂外部
  资料」的定位不同，且易污染知识库）——均列后续。
- **B2 格式范围**：`md` / `txt` / `html`；PDF 列第二阶段。
- **B3 触发方式**：**CLI 先行**——`aris knowledge add|list|remove|search`。WebUI 上传
  排第二（后台骨架已有，落盘后调同一个 `knowledge.ingest` 服务，不重复实现）。
  **agent 不给摄入权限**：知识库定位是用户投喂，让 Aris 自己往里塞东西风险与收益
  不成正比；agent 只拿检索工具（见 4.2 D1）。
- **B4 增量与去重**：以**文档**为单位 + **content hash 幂等**：
  - 同路径重摄入：hash 未变 → 跳过；hash 变 → 旧块**软删**（`deleted_at`）后插新块
  - 两张表：`knowledge_docs`（路径 / 标题 / hash / mtime / 状态）与
    `knowledge_chunks`（块 + FK → doc）
  - **不做**向量级去重（成本高、收益低）

### 5.2 C. 存储与切分

- **C1 向量维度：384（本地 Bekko）**。理由（用户决策）：**云端是给 `memory/` 冷侧
  用的，与知识库无关**；且 Cloudflare 可能断联，走云端需额外写断联降级逻辑。代价与对策：
  - 本地 Bekko 属**重依赖**（sentence-transformers / OpenVINO，常驻约 1.5 GiB），
    放 dependency-group `embedding` 并默认安装；`store/` 对其
    **懒加载**，依赖缺失时给出可读提示（见 3.3 实现状态）
  - 本地 embedding 批量摄入是 CPU 密集型（`EMBEDDING.md` 实测连续压力约 1164% CPU）
    → 摄入**串行 / 限并发**，必要时降优先级，避免打满主机
  - 表结构**按维度参数化**（`store/` 提供建表 helper，维度取自 provider），日后换
    维度只需重建该表 + 重摄入，代码不动
- **C2 分块策略**：**标题层级切 + 定长兜底重叠**。md 按 `##`/`###` 切 section，超长再
  按段落切，overlap ≈15%；纯文本 / HTML 按段落聚合到 500–800 字符。块保留
  `heading_path`（如「安装 > 依赖」）并在检索结果中展示，提升可引用性。
  **不做**语义切分（需额外模型、收益不稳）。
- **C3 元数据字段**：`doc_id` / `source_path` / `source_hash` / `source_mtime` /
  `title` / `heading_path` / `chunk_index` / `char_count` / `content_hash` /
  `ingested_at` / `deleted_at`，另留 `meta jsonb` 兑将来（沿用「表结构预留宽松」）。
- **C4 索引与参数**：HNSW + `vector_cosine_ops`，`m=16` / `ef_construction=64`（先用
  pgvector 默认值跑通再调）；查询期 `ef_search` 可调（默认 40）；top-k 默认 5；
  **初期不设相似度阈值**（避免误杀）。**先导数据、后建索引**。

### 5.3 实现次序（2026-09-18 定案）

**`store/` 底层先行**：PG 环境 bootstrap → 连接池 → 迁移 → embedding provider →
建表 helper，跑通后再做 `knowledge/` 的摄入与检索；`memory/` 随后复用同一底层。

---

## 6. 商讨结论记录

> 每达成一项结论，在此登记（日期 + 结论 + 影响范围），并同步到
> `AGENTS.md`「已定案」与 `PROGRESS.md`。

| 日期 | 议题 | 结论 | 影响 |
|---|---|---|---|
| 2026-09-14 | 定位 | 面向外部资料的**独立 RAG 知识检索能力**，与个人记忆分开 | 需明确与 `memory/` 的边界（A1） |
| 2026-09-18 | 数据库部署（原前置阻塞） | **micromamba + conda-forge** 便携 PostgreSQL + pgvector，脚本探测缺失后自动获取，不依赖系统安装（见第 3 节） | 前置阻塞解除；代码只认 DSN，不影响 A/B/C/D |
| 2026-09-18 | A1/A2/A3 边界与归属 | 新建 **`store/`**（embedding + PG 基础设施）+ **`knowledge/`** 两模块，共享底层、依赖单向；**不做 skill**，经大总线暴露；开关 `config/knowledge.toml: enabled` | 目录结构与服务表定型；`memory/` 后续复用 `store/` |
| 2026-09-18 | D1/D2/D3/D4 检索侧 | agent 工具**自主调用**（无自动注入）；第一阶段**纯向量**；结果格式沿用 web_search 约定 + **必带来源**；与记忆**两条独立通路** | 对外契约定型；`knowledge_search` 工具与 `store.embed` 服务可直接实现 |
| 2026-09-18 | B1–B4 摄入侧 | 本地文件/目录 + HTML 起步（**无 PDF / 目录监听 / 对话沉淀**）；**CLI 先行**，**agent 不给摄入权**；content hash 幂等 + **软删重建** | 摄入链路定型；`knowledge_docs` / `knowledge_chunks` 两表 |
| 2026-09-18 | C1–C4 存储与切分 | 维度 **384 本地 Bekko**（不占云端）；标题层级切 + 定长兜底重叠；元数据 11 字段 + `meta jsonb`；HNSW cosine `m=16` / `ef_construction=64`，先导数据后建索引 | 表结构定型；本地 embedding 列可选依赖 + 摄入限并发 |
| 2026-09-18 | 实现次序 | **`store/` 底层先行**，再做 `knowledge/`，`memory/` 随后复用 | 下一步进入实现 |

（待续）
