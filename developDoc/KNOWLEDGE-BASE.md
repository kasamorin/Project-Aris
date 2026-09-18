# 知识库（Knowledge Base）—— 商讨稿

> **状态：商讨中，未定案。本文件是待商讨的议题清单，不是设计结论。**
> 讨论出结论前**不要照此实现**。结论落定后请把对应小节改写为「定案」，
> 并在 `AGENTS.md` 的「已定案」中登记一句摘要。

- 起始日期：2026-09-14
- 开发分支：`feat/knowledge-base`（从 `develop` @ `7f0b4dd` 拉取）
- 阶段：**概念商讨 / 方案准备**，尚未写代码

---

## 1. 背景与定位

2026-09-14 用户提出要为 Aris 做「知识库」。经确认，其定位是：

> **面向外部资料的独立 RAG 知识检索能力** —— 与 Aris 的**个人记忆分开**，
> 走 embedding + 向量检索，用于让 Aris 检索并引用用户投喂的资料。

这与两处既有记录相关但**都不等同**，商讨时需明确对齐：

| 既有记录 | 关系 |
|---|---|
| `SKILLS.md` 演进待办「知识库做成独立 skill」 | 旧定位是 skill 形态；知识库需要**常驻检索服务**，如何结合待定（议题 A3） |
| 开发路线第 4 项 **记忆系统**（`memory/`） | 知识库是**独立能力**，但底层向量与数据库设施大概率共享；边界待定（议题 A1） |

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
- **重依赖不进主依赖**：sentence-transformers / openvino 等按需作为可选或独立环境安装
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

- `postgresql` 与 `pgvector` **同源**，版本匹配由 solver 保证（实测 `pgvector 0.8.6`
  有 linux-64 / linux-aarch64）
- 由 **micromamba 单文件静态二进制**驱动，**免 root、免编译**，安装到 `data/pg/`
  （`.gitignore` 已覆盖 `data/`，仓库零体积增长）
- 首次下载约 **300MB**（已接受，走单一路径；不保留"系统 pacman 优先"的双路径分支）

**pgvector 直接取 conda-forge 预编译包，不源码编译。** 依据（已读源码确认）：
pgvector 在 glibc Linux + GCC/Clang 上会自动启用 `USE_TARGET_CLONES`
（`src/halfvec.h`），生成 `target_clones("default", "fma")`，**运行期按 CPU 选 FMA
快路径**，通用编译的包同样吃到 SIMD。而本机 CPU 为 Xeon E5-2673 v3（Haswell-EP），
**无 AVX-512**，`-march=native` 相比 `target_clones` 无额外收益。

> 可选后手（当前不需要）：若日后换到支持 AVX-512 的 CPU，可用该 PG 的 `pg_config`
> 源码编译 `make OPTFLAGS="-march=native"` 覆盖，收益量级约 10~20%。

### 3.3 脚本职责（幂等）

- `scripts/pg-bootstrap.sh`：探测 → 按需装 micromamba → 装 PG + pgvector 到
  `data/pg/` → `initdb`（UTF8、本地 trust、socket 落 `data/pg/run`）→ 起服务
  → `createdb aris` → `CREATE EXTENSION vector` → 版本清单写 `data/pg/versions.txt`
- 服务端口用项目专用端口（如 **55432**），避开将来系统 PG 的 5432
- **下载必须校验 sha256**（常量写死脚本内，升级时人工更新并记 `PROGRESS.md`）
- 生命周期收成 CLI 子命令 `aris db start|stop|status|psql`（与"CLI 是统一入口"
  一致），shell 脚本仅作底层实现
- Python 侧依赖 `psycopg[binary]`（自带 libpq，不依赖系统 libpq）+ `pgvector` 适配包

### 3.4 边界

- **代码只认 DSN**，不感知是系统实例还是便携实例 → 本决策**不影响议题 A/B/C/D**
- WebUI 的「psql 未安装」提示保留，但降级为**兜底**：正常路径是引导用户执行
  `aris db init`

---

## 4. 待商讨决策点

> 标记：**A / D 属边界性与对外接口**，改动成本最高，建议优先商讨；
> **B / C 属内部实现**，可先拍粗方向，等最小闭环跑通再调。

### A. 边界与归属（决定目录结构）

- **A1** 知识库与 `memory/` 是**共享底层**（embedding 抽象 + pgvector 连接复用，
  表和语义层分开），还是各自一套互不依赖？
- **A2** 代码落在哪：`memory/` 下的子层 / 独立 `knowledge/` 模块 /
  `core/` 放检索基础设施再由上层各自调用？
- **A3** 与 `SKILLS.md` 旧定位对齐方式：知识库做成 skill（包一层工具）、
  还是直接注册总线服务 `knowledge.search`，或两者并存？

### B. 摄入侧（谁是数据入口）

- **B1** 数据来源：本地文件投喂 / 目录监听 / 网页存档 / 从对话自动沉淀？
- **B2** 格式范围与优先级：md / txt / pdf / html？
- **B3** 触发方式：CLI 命令（如 `aris knowledge add`）/ WebUI 上传
  （后台骨架已有）/ agent 自主工具？
- **B4** 增量与更新：文档改动后如何处理（全量重建 / 版本化 / 软删除）、如何去重？

### C. 存储与切分（内部实现）

- **C1** `knowledge_chunks` 表用哪个维度——1024（冷模型，批量摄入天然归冷侧）
  还是 384？
- **C2** 分块策略：按标题层级 / 固定长度带重叠 / 语义切分，chunk 多长？
- **C3** 元数据字段：来源路径、标题、位置、时间、内容 hash 等取哪些？
- **C4** 表结构与索引：HNSW / IVFFlat，检索参数（top-k、相似度阈值）。

### D. 检索侧（决定对外接口）

- **D1** 暴露方式：agent 工具 `knowledge_search`（与 `web_search` 并列、自主调用）/
  每轮自动 RAG 注入上下文 / 两者并存但定优先级？
- **D2** 算法：纯向量 / 向量 + PostgreSQL 全文检索混合（零新依赖）/
  增加 rerank 模型（引入新依赖）？
- **D3** 结果入上下文的格式：是否沿用 `web_search` 已确立的
  「外层 JSON 标识类型 + 内部 markdown 省 token」约定？
- **D4** 知识检索与记忆检索是合并为统一入口，还是保持两条独立通路？

---

## 5. 商讨结论记录

> 每达成一项结论，在此登记（日期 + 结论 + 影响范围），并同步到
> `AGENTS.md`「已定案」与 `PROGRESS.md`。

| 日期 | 议题 | 结论 | 影响 |
|---|---|---|---|
| 2026-09-14 | 定位 | 面向外部资料的**独立 RAG 知识检索能力**，与个人记忆分开 | 需明确与 `memory/` 的边界（A1） |
| 2026-09-18 | 数据库部署（原前置阻塞） | **micromamba + conda-forge** 便携 PostgreSQL + pgvector，脚本探测缺失后自动获取，不依赖系统安装（见第 3 节） | 前置阻塞解除；代码只认 DSN，不影响 A/B/C/D |

（待续）
