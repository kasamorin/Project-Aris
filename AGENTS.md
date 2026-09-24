# AGENTS.md

本文件是项目**所有通用要求**的唯一权威来源，每个会话启动时自动阅读。
开发具体模块时，只需按需阅读「文档索引」中的专门文档，无需再辗转其他文档获取通用要求。

## 环境识别（会话开始第一步）

- 默认开发环境：**Arch Linux（Wayland 桌面）**，bash 完全可用，一切命令（含 git）
  可自由执行，无需特殊限制。
- 会话开始先执行 `echo ok` 测试 bash 是否可用：
  - 正常返回 → 执行 `fastfetch` 确认当前环境（Arch / Termux），据此按需遵守下方规则；
    若 `fastfetch` 不可用，回退用 `uname -a`、`/etc/os-release` 等判断。
  - 超时/卡死 → 视为 bash 不可用，直接按「Termux 注意事项」处理。

### Termux 注意事项（安卓次环境）

- bash 工具**可能**卡死（超时 120s 无输出）。
- 只要任意一个 bash 命令能正常返回不超时，即可自由按需执行（包括 git）。
- 若测试命令超时/卡死，则视为 bash 不可用：避免用 bash，尤其禁止 git 命令；
  需要提交时把命令与提交信息写好交给用户手动执行。
- 文件操作优先用 read/write/edit/glob 工具；glob 偶发失败时改用 read 目录。

## 项目简介

- 拟人 AI「Aris」，参考 Neuro-sama，目标是「社会学意义上的人」：长期独立人格、
  持续演进的世界观、人际关系网和成长轨迹
- 纯个人项目，但可维护性为最高优先级，目标运行数年
- 开发节奏：先跑通核心链路（STT → LLM → TTS），再逐层叠加能力
- **交互形态**：最终以**语音为主**（STT → LLM → TTS），文字为辅且不通过 TUI，
  而是接入外部平台（Matrix / Discord 等）。TUI 定位为**开发调试手段**，
  WebUI 定位为**运维管理后台**（非对话界面）
- 详细蓝图见 `developDoc/Project-Aris.md`

## 开发环境

- 主环境：Arch Linux（Wayland 桌面）——**默认开发环境**
- 次环境：Termux（安卓），**仅用于没有电脑时改文档**；不运行代码，无需兼容
- **本机注意（2026-09-18）**：KDE **Baloo** 默认索引整个 `$HOME`，批量 `uv sync` /
  下载大文件后 `baloo_file_extractor` 会涨到数 GB 且长时间不退出（实测 3.4GB / 34min，
  杀掉重启 90 秒又涨回 3GB）。**处置**：`~/.config/baloofilerc` 排除
  `$HOME/Codes/Project-Aris/data/` 与 `$HOME/.cache/`（备份
  `baloofilerc.bak-20260918`），并 `balooctl6 config set contentIndexing no`
  **关闭内容索引**——extractor 不再启动，baloo 内存从 ~3.8GB 降到 130MB。
  代价：KRunner 搜不了文件**内容**（文件名搜索照常）。
  恢复内容索引：`balooctl6 config set contentIndexing yes`

## 现状

- 当前版本 **v0.4.2（beta，2026-09-24）**。**这是首个「clone 下来一条命令起服务」的
  版本**：`uv sync` → `cp .env.example .env` → `aris serve` 即可（首次自动获取便携 PG，
  需联网数分钟），WebUI 落在 `http://127.0.0.1:9690`。**自本版起正式区分 beta 与正式版**
  （0.x 全为 beta，正式版自 v1.0.0 起，tag 带 `-beta` 后缀），见「版本号更新」。
- 骨架、LLM 接入、文字对话、行为扩展（函数调用）、联网搜索、人格系统均已完成。
- **启动编排 `serve/` 已完成（v0.4.1）**：`aris serve [--only/--skip/--dry-run]` 一条命令
  拉起 PG（缺则自建、没跑则自启、退出只停自己拉起的）、后台预热 embedding、建知识表、
  并入 WebUI（端口冲突则拒启 web 并提示）；`aris doctor` 与它共用同一份探针。
  详见 `developDoc/SERVE.md`。
- WebUI 管理后台已完成（2026-08-23）：登录鉴权、仪表盘、审计、提供商管理、
  技能管理、配置管理、日志查看；**知识库管理页 `/knowledge` 已补（2026-09-18）**。
- **WebUI 安全审查与总线化改造已完成（2026-08-30）**：路径穿越/TOML 注入/XSS/
  鉴权绕过等安全漏洞全部修复；webui 全部路由改走 `core.call`（16 个总线服务 +
  启动自检）；新增 11 个关键路径测试（总计 48 通过）；pre-commit 分支保护 +
  `scripts/release-check.sh` 发布检查落地。详 `developDoc/SECURITY-AND-REFACTOR-PLAN.md`。
- **知识库（Knowledge Base）已落地（2026-09-14 起商讨，2026-09-18 实现）**：定位为
  **面向外部资料的独立 RAG 知识检索能力**，与 Aris 个人记忆**分开**。全部议题与部署
  方式定案见 `developDoc/KNOWLEDGE-BASE.md`；`store/` 底层 + `knowledge/` 首期
  + agent 工具 + WebUI 知识库页均已跑通（v0.4.0 发布内容）。
- **数据库地基已跑通（2026-09-18）**：`store/` 的便携 PostgreSQL 17.11 + pgvector 0.8.1
  就位，`aris db init|start|stop|status|psql` 可用；本地 embedding（Bekko a25m，384 维）
  也已跑通（`aris store info|embed`）。**`store/` 三块地基（PG 环境 / embedding /
  迁移 + 向量检索 helper）已齐**。
- **知识库首期可用（2026-09-18）**：`knowledge/` 两表 + 分块 + 摄入 + 检索全链路跑通，
  CLI `aris knowledge add|list|remove|search|reindex`；agent 工具 `knowledge_search`
  已接入并用脚本化 mock 验证工具往返；**WebUI 知识库页 `/knowledge` 也已落地**
  （上传 → 后台摄入 → 轮询进度 → 列表/移除/检索试验/重建索引）。
- 最新进度、当前阻塞、待定决策、下一步 → 见 `PROGRESS.md`（每次开发前先读）。

## 编码约定（唯一权威，必须遵守；原 CODING-GUIDELINES.md 已并入本文）

### 注释
- 介于「关键逻辑写注释」与「详细注释」之间
- 复杂算法、业务逻辑、易误解处尽量写清楚注释
- 简单代码不写废话注释

### 语言
- 变量/函数/类名一律使用英文
- 注释一律使用中文
- 模块/函数/类的 docstring 一律使用中文

### 代码风格
- 行宽限制 100 列
- 类型标注（type hints）尽量多标注：所有公开函数/类标注完整类型
- C 代码用 clang-format 格式化（仓库根 `.clang-format`，行宽 100）
- C 命名规范：
  - 函数：大驼峰（`ArisDemoAdd`）
  - 变量：小驼峰（`userCount`）
  - 指针声明：星号靠变量（`int *p`）
  - 常量/宏：UPPER_SNAKE_CASE（`MAX_BUFFER_SIZE`）
- Python 静态检查/格式化工具：**待定**（候选：ruff / black+isort+flake8），定案前不引入

### Git 开发流程（2026-08-14 定案）
- **提交信息**：Conventional Commits 完整格式（head + body）：
  - head：前缀 + 简短中文描述，如 `feat: 添加登录功能`；前缀允许
    `feat|fix|docs|refactor|chore|test|build|ci|perf|style|revert`，
    可带 scope（`feat(bus): ...`）
  - body：换行后用中文写清改动动机与要点（为什么改、改了什么）
  - 改动极小（body 无内容可写）时可省略 body，但 head 必须符合格式
  - **仓库自带 commit-msg hook**（`.githooks/`）校验 head 格式，安装方式见
    `scripts/install-git-hooks.sh`；hook 放行 merge/revert 提交
- **分支策略（2026-08-14 优化，git flow 简化版）**：
  - **`develop` 为日常开发汇聚分支**：所有开发先在 feature 分支
    （`feat/`、`fix/`、`docs/`、`refactor/` 前缀，从最新 develop 拉取），
    分支内小粒度提交，验证后 `git merge --no-ff` 合并回 develop，
    随后删除本地 + 远程 feature 分支。**daily 开发一律不直接碰 main**。
  - **`main` 永远稳定可跑，只进版本发布**：仅在**版本号更新**（bump
    版本 + 打 tag）时才从 develop 合并回 main（`git merge --no-ff`），
    合并提交用对应前缀一句话总结。日常 fix/docs 不进 main。
  - 小版本（feature 级）bump patch（如 0.2.1 → 0.2.2），大功能/破坏性
    变更 bump minor；**避免为了「有进展」频繁 bump**，攒到阶段性发布再 bump。
- **版本与 tag**：版本号唯一源与 bump 方式见下节「版本号更新」。发布时：
  develop 上 bump 版本 → 合并回 main → 打 `vX.Y.Z` tag → push。
- **发布前检查（2026-08-30 起）**：`bash scripts/release-check.sh` 校验版本号
  单一来源结构 + 已安装元数据一致 + `uv lock --check` + 当前分支为 develop
  + 无未合并 feature 分支 + 目标 tag 未占用；通过再走发布流程。
  `.githooks/pre-commit` 负责分支保护（main 禁直接提交，develop 直提警告），
  换机后 `bash scripts/install-git-hooks.sh` 一次装齐。
- **保留分支**：`oldWish` 为历史保留分支（main 祖先：首次提交/README/许可证），
  **不要删除**，也不建议在此分支上继续开发。

### 版本号更新（2026-09-24 定案）

> 第三条开发规范。背景：版本号曾在 `pyproject.toml` / `src/aris/__init__.py` /
> `uv.lock` **三处各写一遍**，0.2.0 / 0.2.2 / 0.2.6 每个版本都要额外的
> 「同步 uv.lock / `__version__`」提交，v0.4.1 还误把版本行混进了功能提交。
> **检查脚本只能治症状，于是改成结构上只剩一处。**

- **唯一源：`src/aris/__init__.py` 的 `__version__`**（一行字面量）。
  - `pyproject.toml` 走 `dynamic = ["version"]` +
    `[tool.setuptools.dynamic] version = {attr = "aris.__version__"}`，**不再有
    静态 `version` 行**；
  - **`uv.lock` 不再记录本项目版本**（dynamic 版本不进锁文件），因此「三源同步」
    这个动作本身消失了，也不再有同步提交。
- **改版本只用 `bash scripts/bump-version.sh <版本|patch|minor|major>`**：
  校验在干净的 develop 上、版本合法（PEP 440 的 `X.Y.Z`）、目标 tag 未占用，
  然后改源 + `uv lock` + `uv sync`，最后打印提交与发布命令。**只改文件不提交。**
- **`[tool.uv] cache-keys` 必须含 `src/aris/__init__.py`**：uv 默认只按
  `pyproject.toml` 判定缓存，少了这一行改了版本也不会重建元数据（实测踩过，
  `aris --version` 与已安装的 `aris==X` 会不一致）。
- 版本号必须是 setuptools 能解析的 PEP 440 形式：`9.9.9-test` 之类会直接构建
  失败（`InvalidVersion`），bump 脚本因此只放行 `X.Y.Z`。
- 校验点全部在 `scripts/release-check.sh` 里，**发版前必跑**；上面那条 trap
  （cache-keys）与「已安装元数据是否跟得上」都有对应检查项。
- **tag 命名与 beta 标记（2026-09-24 定案）**：本项目的运行方式是 **clone 仓库**
  而非下载 release，所以 beta 必须在 **tag** 上可见。
  - `0.x` 阶段每个版本都是 beta → tag 带后缀：`v0.4.2-beta`（同版本只发一次，故不编号）；
  - `v1.0.0` 起：正式版 `vX.Y.Z`；预发布 `vX.Y.Z-beta.N`，且 `__version__` 同步写
    PEP 440 预发布形式（如 `1.3.0b1`），使 tag 与运行时版本**一一对应**——否则
    `aris --version` 分不出自己是 beta 还是正式版；
  - 规则实现在 `scripts/lib-version.sh`，`bump-version.sh` 与 `release-check.sh`
    共用同一份，避免两处各写一遍。

### 歧义处理
- 遇到不确定的需求或歧义，先停下来问用户确认，绝不擅自假设

### 验证
- 具体情况具体判断
- 改动可能影响运行时，必须运行验证
- 涉及业务逻辑的改动：运行 `uv run pytest` 确认无回归
- 纯文本/文档改动不需要验证

### 开发节奏
- 动态平衡：先建基础模块跑通，大方向架构先定好，功能之后逐步完善
- 不为不存在的需求设计（YAGNI），但基础架构方向要提前明确

### 重构态度
- 分层处理：
  - 重要基础/核心模块：发现不满尽量尽早重构（越晚返工成本越高）
  - 外围模块：记入待办，延后重构
- 总体原则：能跑就不动，除非它开始阻碍后续开发或影响正确性

### 轮子哲学
- 按规模决定：
  - 小功能自己写
  - 重活（数据库、语音、LLM SDK 等）用成熟库

### 错误处理
- 分层处理但更严格：
  - 核心逻辑：快速失败、不留脏状态，错误越早暴露越好
  - 外围功能：宽容降级，保证不崩溃
- 具体场景具体判断

### 代码审美
- 工程性优先：追求健壮、可维护、易调试，实用至上
- **KISS 原则**：一个东西只做一件事，每处代码职责单一
- 不写聪明的花活

### 项目定位
- 纯个人项目，但可维护性是最高优先级
- 目标运行数年：模块边界清晰、命名自解释、文档跟上
- 让几年后的自己仍能读懂每一段代码

## 技术栈（已定，勿自行更改）

- 编程语言：Python 为主；C 语言辅助（性能敏感处），必要时 TypeScript
- Python：最低 3.12，开发按 3.14，尽量用新特性
- 依赖管理：uv；包布局 src 布局，包名 `aris`
- 配置：pydantic-settings（已定案，详见下节「配置系统方案」）
- 日志：loguru
- 测试：pytest（2026-08-18 启用，`uv run pytest` 运行，用例在 `tests/`）

## 配置系统方案（2026-08，已定案）

背景：Termux（aarch64-android，Python 3.14）无 pydantic-core 预编译 wheel，
源码构建需 Rust（不可行），Termux 仓库亦无 python-pydantic 包（已实测）→
pydantic-settings 在 Termux 无法安装。分级方案：

1. **第一选择**：pydantic-settings（PC / Linux 桌面可装）
2. **第二选择**：标准库实现（dataclass + 手写 .env 解析，约 30 行，零依赖，两平台通吃）
3. **最后备选（野路子）**：C 语言模拟配置解析（ctypes 接入，不推荐：文本解析用 C
   违背 KISS，增加编译依赖，可维护性差）

**定案（2026-08-09，Arch Linux 实测）**：选第一选择 pydantic-settings。Arch 上
`uv sync` 已跑通（pydantic-settings 2.15.0 / pydantic 2.13.4 / Python 3.14.6）。
Termux 无法安装 pydantic-settings 的问题暂缓，若后续 Termux 成为必要运行环境，
再评估第二选择（届时 pydantic-settings 分支迁移成本低，见下注）。

> 注：config.py 的字段只依赖 `BaseSettings` 的简单 env 读取语义，若未来迁移到
> 标准库实现，仅需重写 `Settings` 类的读取逻辑，调用方（`get_settings()`）不变。

### 配置体系（2026-08-12 定案：三个配置源各管一摊）

| 配置源 | 管什么 | 状态 |
|---|---|---|
| `.env`（`ARIS_` 前缀，pydantic-settings） | 启动级参数、密钥、`data_dir`、`llm_providers_file` | 已有 |
| `config/providers.toml` | LLM 提供方（base_url/key env 名/超时/transport/模型） | 已移入 config/ |
| `config/*.toml`（模块级，tomllib 加载） | 功能可调参数：chat / search / logging / audit / notify | 新建 |

- 模块级 toml 优先级：**代码内 dataclass 默认值 < `config/*.toml`**，
  缺文件/缺键静默用默认；加载器 `aris/cfgtoml.py`（零新依赖）。
- 收口原则：**枚举=代码 StrEnum**（逻辑类型不进配置）、**实现细节=模块顶部常量**、
  **真正可调参数才进 toml**。密钥永远只在 `.env`。
- 详情见 `developDoc/CONFIG.md`。

## 数据与密钥

- 运行时数据（日志、数据库文件等）统一放 `data/`，**不进 git**
- 密钥（API key）一律放 `.env`，同样不进 git；配置读取用 `ARIS_` 前缀环境变量
- 备份建议：定期 `rsync -av data/ /backup/aris-data/`；将来用 PostgreSQL 时用 `pg_dump`

## 模块划分（对应 Project-Aris.md 蓝图）

- `core/` —— 基础设施：跨模块通讯总线 CMCB（`bus.py` 服务注册表 + 事件总线 +
  审计）+ LLM 提供方抽象（多提供方 fallback、流式、工具调用）
- `store/` —— **存储与向量基础设施（2026-09-18 定案）**：embedding 抽象
  （文本 → 向量，Protocol + 多实现）+ PostgreSQL/pgvector 基础设施（DSN、连接池、迁移、
  向量检索 helper）。**不认识 `memory/` / `knowledge/`**，不做业务语义；模型本体放
  `data/models/`（不进仓库）。经总线暴露 `store.embed` / `store.health` / `store.migrate`
  - 已实现（2026-09-18）：环境探针（`pgenv`）、便携实例获取（`bootstrap`，
    micromamba + conda-forge）、连接探活（`db`，总线 `store.health`）、
    CLI `aris db init|start|stop|status|psql`；实测 PG 17.11 + pgvector 0.8.1
  - 已实现（2026-09-18 续）：embedding 抽象 + 本地 Bekko provider（384 维，懒加载；
    重依赖为 dependency-group `embedding` 且默认安装）、`aris store info|embed`
  - 已实现（2026-09-18 续二）：迁移机制（`migrate.py`：按 owner+version 记录、
    单事务应用、防历史改写）与 pgvector helper（`vector.py`：建 HNSW 索引 / upsert /
    近邻检索 / 维度读取；标识符校验 + 算子白名单）、CLI `aris db migrate`；
    总线服务合计 10 个（`store.health` / `store.embed` / `store.embed_dimension` /
    `store.connect` / `store.migrate.*` / `store.vector.*`）
  - 待实现：无既定项（将来按需扩展，如云端 provider）
- `memory/` —— 记忆系统：Embedding + 数据库（复用 `store/`，不自建第二套）
- `knowledge/` —— **知识库（2026-09-18 定案，首期已实现）**：面向外部资料的独立 RAG
  检索，含摄入、分块、来源管理、检索语义。**不做 skill**（属内部底层设施，经大总线
  暴露 `knowledge.ingest` / `knowledge.sources` / `knowledge.remove` /
  `knowledge.search` / `knowledge.reindex`）；启用开关为
  `config/knowledge.toml` 的 `enabled`。**向量维度 384（本地 Bekko，非云端）**，
  摄入走 CLI（`aris knowledge add|list|remove|search|reindex`），
  **agent 只拿检索工具、不给摄入权**。
  - 已实现（首期）：两表迁移（`knowledge_docs` / `knowledge_chunks`）、
    分块（标题层级 + 定长兜底重叠）、md / txt / html 载入、摄入（hash 幂等 +
    软删重建）、列举 / 移除 / 纯向量检索（带来源标识）
  - 已实现（续）：agent 工具 `knowledge_search`（D1：与 `web_search` 并列、
    **Aris 自主调用**，不做每轮自动注入；返回外层 JSON + 内部 markdown，
    每条带来源路径、标题层级与距离）
  - 已实现（续二）：WebUI 知识库页 `/knowledge`（上传落盘 `data/knowledge/` +
    后台摄入 + 轮询进度、文档列表与移除、检索试验、重建索引）
  - 待实现：PDF 与混合检索（第二阶段）
  详见 `developDoc/KNOWLEDGE-BASE.md`
- `voice/` —— STT（语音识别）、TTS（语音合成）
- `persona/` —— 人格系统（提示词工程起步，2026-08-12）：注册
  `persona.system_prompt` 服务，其他模块经 `core.call` 取人设，不再硬编码；
  世界观/人际关系/成长轨迹后续在此演进
- `behavior/` —— 行为（函数调用已实现）：`registry.py` 工具注册表、`loop.py` agent loop
  （LLM↔工具循环）、`tools/` 内置工具集、`skills/` 技能系统（2026-08-12 落地：
  目录化 skill，`SKILL.md` + 可选 `tools.py`；`SkillManager` 发现/菜单/激活，
  三层渐进式披露，详见 `developDoc/SKILLS.md`）；MCP 后续作为工具来源注册进 registry
- `chat/` —— 文字对话（已实现）：`session.py`（会话逻辑）、`tui.py`（全屏界面）、
  `commands.py`（指令）；CLI 走 `aris chat`，连接仍走 `core/`。非终端自动回退 input 循环。
  **TUI 定位为开发调试手段**，项目成型后的主要对话界面是 WebUI（见 developDoc/WEBUI.md），
  TUI 保留作为无 GUI 环境下的调试与快速验证入口
- `serve/` —— **启动编排（2026-09-19 定案，首期已实现）**：`aris serve`
  [--only] [--skip] [--dry-run] 把各模块按序拉起（PG 自启 + 迁移、embedding 后台预热、
  knowledge 建表、WebUI 并入、端口冲突则拒启 web），前台打印启动清单与日志、Ctrl-C 收尾；
  无阻塞步骤时不执行收尾（数据库保持运行）。**单向**：只调别人的启动动作，
  **不对外提供查询服务**；**非守护**、不含 TUI。失败分级（required = `services`
  自检与 `store.db`，其余 optional）+ **降级必须记日志**。组装根与依赖清单已上收：
  `serve.assemble()` 是唯一触发点、`services` 步骤核验各模块声明的
  `REQUIRED_SERVICES`、`aris doctor` 与 `aris serve --dry-run` 共用
  `serve.probe_all()` 探针。**待做**：工具注册表 / agent loop / LLM engine 仍是
  会话级对象（#4/#7 时由 serve 上收）。详见 `developDoc/SERVE.md`
- 插件系统：**后续可能增加**——MCP 服务器可做同样的事，
  届时再评估是否独立成模块

### 模块间调用规则（跨模块通讯总线 CMCB，2026-08-12 定案）

- 模块间通讯**一律走 `core.call` / `core.provide`**，不直接跨模块 import 调用
- 核心类实例自注册（`__init__` 里 `provide` 自己的方法），命名 `module.service`
- 明确不走总线的边界：对象构造/装配（依赖注入）、同模块内部调用、纯类型引用
  （如 Message）；CLI 组装根可保持直接引用
- 服务表与架构详见 `developDoc/CMCB.md`

## 独立文档站（规划中，未开工）

- **不在本仓库内**：面向使用者 + 插件作者的独立站点，另起仓库、**VitePress**，
  本仓库不为其提供构建产物，也不与仓库内文档做同步机制。
- 与本文档的分工：`README.md` 给使用者最短路径，`developDoc/` 留「为什么这么设计」
  与踩坑（给改本仓库的人），**文档站讲「契约是什么、怎么写插件」**；内容全部新写。
- 关键结构约束（**起站时照做，事后改代价最大**）：根路径 = 当前开发版，
  历史版本在 `/vX.Y/`；链接一律相对、sidebar 需按版本前缀生成。
- 服务表**不在站点上一开始全暴露**，只呈现插件可用的契约面。
- 完整决策（URL 布局 / 版本节奏 / 坑 / 待办）见 `developDoc/DOCS-SITE.md`。
- 与插件系统的关系：站点上「插件作者契约」可先写，**当作工具去推平
  `PLUGIN.md` 的 `[待讨论]` 项**——契约落地后再改就要动代码。

## 开发路线

> **当前聚焦：`aris serve` 已完成（v0.4.2 beta，clone 下来一条命令起服务）**；
> 下一步候选：真 API 实测（等低成本方案）/ 知识库第二阶段（PDF、混合检索）/
> 记忆系统（`memory/` 复用 `store/`，动手前先定人格与会话的持久化载体）。
> WebUI 管理后台见 `developDoc/WEBUI.md`，启动编排见 `developDoc/SERVE.md`。

1. **搭标准项目骨架**（轻量）：目录结构 + 配置系统 + 日志 + CLI 入口，各模块留占位
   - 骨架已完成（2026-08），配置系统已定案并跑通 `uv sync`（2026-08-09）
2. 接入 LLM —— **已完成**（2026-08-09，`core/llm`，见 PROGRESS.md）
3. 跑通文字对话 —— **已完成**（2026-08-09，`aris chat`，见 PROGRESS.md）
4. 记忆系统（PostgreSQL + pgvector）—— **下一步**
5. 人格系统 —— **提示词工程起步，已完成简单版**（2026-08-12，`persona/`）；
   世界观/人际关系/成长轨迹后续演进
6. 语音链路（STT → LLM → TTS）
7. 行为扩展（函数调用 / MCP 服务器 / Skills）—— **函数调用已完成**（2026-08-09），
   MCP / Skills 待后续；联网搜索已完成（Bing 直连 + Tavily 兜底）
8. GraphRAG
9. 知识库（独立 RAG 知识检索）—— **已完成首期（2026-09-18，随 v0.4.0 发布）**：
   `store/` 三块地基（PG 环境 / embedding / 迁移 + 向量检索 helper）+ `knowledge/`
   （两表、分块、摄入、检索）+ agent 工具 `knowledge_search` + WebUI 知识库页
   `/knowledge`。**待续**：PDF 与混合检索（第二阶段）。
   详见 `developDoc/KNOWLEDGE-BASE.md`

## 已定案（直接照做，无需再确认）

- **Embedding（2026-08-09）**：按记忆层级分 provider——热记忆本地
  Bekko a25m（OpenVINO CPU），冷记忆云端 Cloudflare BGE-M3；
  两库维度不同（384/1024）各建独立 pgvector 表，互不混用。
  实现 memory 模块时直接按此方案，详见 `developDoc/EMBEDDING.md`
- **LLM 连接（2026-08-09）**：选型定案——多提供方抽象 + fallback，本次实现
  OpenAI Chat Completions 格式（v1/chat）。统一请求模板（Message/ChatRequest）
  + formatters 按 format 翻译；双传输（openai SDK 默认 / httpx 手写）；流式；
  报错切下家 + 总体超时预算；错误处理返回预设提示语 + 广播（弹窗/推送接口）。
  配置在 `providers.toml`（toml 结构 + `.env` 密钥），CLI `aris llm test` 验证。
  详见 PROGRESS.md
- **配置系统（2026-08-09）**：pydantic-settings，Arch 上 `uv sync` 已跑通
- **工具调用（2026-08-09）**：原生 tool_calls 为主，手动 JSON 模板留作备选
  （提取层留接缝，暂不实现）。流式 tool_calls 分片按 index 拼装，流结束发
  「完成事件」（finish_reason + 完整 tool_calls）；agent loop 放 behavior 模块
  （loop.py + registry.py + tools/）。Message 已补 reasoning_content/tool_calls/
  tool_call_id（DeepSeek 带 tools 必须回传 reasoning_content 否则 400）。
  思考模式默认关闭（`thinking: {"type":"disabled"}`，实测有效），`--thinking` 开启
- **记忆数据库**：PostgreSQL + pgvector 起步；表结构**预留宽松**，
  方便以后加 GraphRAG（Apache AGE vs 递归 CTE 到时再定）
- **记忆实现方式**：走 RAG，但**不用现有框架**（LangChain/LlamaIndex 等），
  自研轻量实现；重量依赖安装方式（独立环境 / pyproject extras）实现时再定
- **数据库部署（2026-09-18）**：**不要求用户预装系统 PostgreSQL**，目标「clone 就能用」。
  由 `store/` 模块按探针链（`ARIS_PG_BIN` → PATH 中 `pg_config`/`postgres` → 项目内
  `data/pg/` → 皆无则 `aris db init` 下载）取用；获取方式定案 **micromamba + conda-forge**
  （`postgresql` + `pgvector` 同源，免 root、免编译、装到 `data/pg/`，gitignore 覆盖）。
  代码只认 DSN，不感知实例来源。**pgvector 取预编译包、不源码编译**：本机
  Xeon E5-2673 v3 无 AVX-512，pgvector 的 `USE_TARGET_CLONES` 已在运行期给出
  FMA 快路径，`-march=native` 无额外收益。详见 `developDoc/KNOWLEDGE-BASE.md` 第 3 节
- **知识库边界与检索接口（2026-09-18）**：新建 `store/`（embedding + PostgreSQL/pgvector
  基础设施）与 `knowledge/`（知识库业务）两模块，依赖单向 `knowledge → 总线 → store`，
  `memory/` 后续复用 `store/`；**知识库不做 skill**（属内部底层设施），能力经大总线
  暴露。检索走 agent 工具**自主调用**（不做每轮自动 RAG 注入）；第一阶段**纯向量**
  （混合检索 / rerank 列第二阶段）；结果格式沿用 `web_search` 约定且**必带来源标识**；
  与记忆检索**两条独立通路**，不合并统一入口。详见 `developDoc/KNOWLEDGE-BASE.md` 第 4 节
- **知识库摄入与存储（2026-09-18）**：来源 = 本地文件/目录 + HTML（**不做 PDF /
  目录监听 / 对话沉淀**）；**CLI 先行**（`aris knowledge add|list|remove|search`），
  **agent 不给摄入权限**（只给检索）；增量 = **content hash 幂等 + 软删重建**，
  两表 `knowledge_docs` / `knowledge_chunks`。**向量维度 384（本地 Bekko），不用云端**
  ——云端是 `memory/` 冷侧的事，且可避免 Cloudflare 断联降级逻辑；本地 embedding 作为
  dependency-group `embedding` **默认安装**、代码侧**懒加载**（未装则该组命令给出可读提示）。
  分块 = 标题层级切 + 定长兜底重叠（保留 `heading_path`）；索引 HNSW + cosine
  （`m=16` / `ef_construction=64`，先导数据后建索引）。**实现次序：`store/` 底层先行**。
  详见 `developDoc/KNOWLEDGE-BASE.md` 第 5 节
- **联网搜索（2026-08-09 定案；2026-08-12 精简；2026-08-14 改 Bing 主链路）**：
  **Bing 直连为主（www.bing.com，零成本无 key）+ Tavily API 兜底**
  （`TAVILY_API_KEY` 走 `.env`）。曾尝试 Playwright 驱动浏览器降级方案
  （原定驱动系统 Firefox，实测官方不支持品牌版，改用自带 Firefox 二进制；
  headless 下 Bing/Google 均触发验证码反爬）——该链路已**代码删除**，
  历史与恢复要点留档在 `developDoc/WEB-SEARCH.md`，勿再实现。
  引擎顺序：`config/search.toml` 的 `prefer_engine`（默认 `"bing"`；可切
  `"tavily"` 或 `"auto"` 按查询语言分流——中文走 Tavily）。Bing 关键实现
  细节（2026-08-14 实测，缺一不可）：Firefox UA（Chrome UA 需 sec-ch-ua
  配套指纹）+ 先访问首页拿 cookie（MUID 会话）+ 搜索 URL 带 `form=QBRE`
  参数；链接解码 `/ck/a` 重定向的 `u=` base64 参数拿真实 URL。不满足时
  Bing 偶发返回官网首页等低质量结果。Bing 失败（限流/断连/无结果）自动
  降级 Tavily。
  工具返回：外层 JSON（`{"type": "web_search_results", "engine", "results"}`）
  标识是联网搜索结果 + 内部 markdown（省 token），每条带自增 id。
  **`web_open(id)` 已实现（2026-08-12）**：按 id 抓取网页正文（httpx +
  trafilatura 提取，过滤导航/页脚/广告），markdown 返回，失败宽容降级。
  id→url 映射为覆盖式缓存（仅最近一次搜索有效）。国内源深抓后续再加。
  agent 可自主多轮换搜索词（试错）。**后续方向**：Google Custom Search JSON
  API 已停新申请（2027-01 停服），可考虑 Gemini API Grounding（每日免费额度）
  接 Google 搜索
- **TTS**：Edge TTS 起步（免费），Azure TTS 备选
- **人格系统（2026-08-12）**：**提示词工程起步**（persona 模块），注册
  `persona.system_prompt` 服务，chat 默认经 `core.call` 取人设，`--system` 可覆盖；
  人设文本轻量结构化（简介/性格/语气/边界），世界观/人际关系/成长轨迹后续演进。
  提示词工程 vs MCP 之争暂以提示词工程落地，未来可按需再议
- **提供商/模型管理（2026-08-14）**：`providers.toml` 顶层 `default_model`
  为默认统一模型 id（CLI 无 `--model` 时用，缺失自动兜底第一可用模型）；
  `LLMModel` 元数据字段 `context_length` / `capabilities`（tools/reasoning/vision）
  / `thinking_default`（None=跟随提供方）。`thinking` 未显式指定时按模型
  `thinking_default` 解析，全路径默认关闭思考（`deepseek-v4-flash-free` 已配
  `false`）。管理命令 `aris llm list` / `aris llm check`。**/models 同步
  （阶段二）**：`aris llm fetch` 一体式（拉取→对比→models.dev enrichment→白名单
  勾选 UI→写回备份）；「本地有云无」模型进退休机制
  `config/retired_models.toml`（机器维护，宽限期 30 天自动删，`aris llm retired`
  手动删，回归自动恢复）。详 `developDoc/LLM-PROVIDER-MGMT.md`
- **总线命名（2026-09-19 收口）**：定名**「跨模块通讯总线」**（Cross-Module
  Communication Bus, **CMCB**）——`core/bus.py` 同时承载服务注册表 + 事件广播 +
  审计查询，按职责命名。文档与代码注释统一用 CMCB 称谓（架构文档
  `developDoc/CMCB.md`）；**代码标识符（模块文件 `core/bus.py`、函数名、服务名）
  保持不变**——服务名前缀是模块名、函数名不含 `aris`，当初即为降低改名成本而设计

## 待定（勿替用户做决定）

- 记忆架构：三层记忆模型（感觉/短期/长期，含反思、遗忘权重、时间线冲突处理）
  用户构想中、未完善、以后可能换
- STT 选型（候选：Groq Whisper / 通义听悟）
- 人格系统实现方式（提示词工程 vs MCP）—— **提示词工程已落地**（2026-08-12，
  persona 模块）；未来是否引入 MCP 按需再议
- **打断 vs 缓存输入策略（未定）**：Aris 流式回复期间用户提前输入的文本，当前
  TUI 直接丢弃（`_discard_pending_input`）。未来可能改为：缓存输入 → 按场景判断
  —— 交给 Aris（相当于「打断 + 继续听」）或丢弃并假装没听见（「装没听见」）。
  判断依据待定（如语气、上下文、用户意图）。实现前先定方案
- Python 静态检查/格式化工具（ruff vs black+isort+flake8）
- **人格与对话历史的持久化载体（未定，2026-09-19 决定先置着）**：人格用
  `data/personas/<id>/` 文件还是 PG 表；会话历史是否落 PG（现为纯内存，重启即丢）。
  做 BACKLOG #4 多人格 / #5 记忆系统**之前必须先定**，否则相关表结构要返工
- ~~总线改名 CMCB~~（已完成：2026-09-19 文档与注释统一改名，见「已定案」）
- ~~测试框架是否启用 pytest~~（已定：2026-08-18 启用 pytest，见技术栈）

## 已知陷阱（踩坑档案，勿重犯）

> 只收**会重复咬人**的坑，一行一条；来龙去脉见 `developDoc/PROGRESS-ARCHIVE.md`
> 对应条目与各专门文档。**新踩到的坑，修完顺手补到这里**（重要的一行进本文，
> 长篇叙述进 PROGRESS 当轮条目，过时再随归档下沉）。

### 数据库 / 迁移（`store/`）
- **迁移「报成功但表不存在」**：psycopg 在已有隐式事务时 `conn.transaction()` 退化为
  SAVEPOINT；建跟踪表后必须先 `commit()`，再逐条跑迁移
- **`pg_isready` 退出码别只认 0**：`1` 也可能是「在跑但拒绝本次探测」（默认库不存在 /
  正在启动），只有 `2` 才算停
- **残留 `postmaster.pid` 会挡住启动**（PID 被复用，`pg_ctl` 直接拒绝）：先探活，
  确认无响应再清 pidfile
- **`pg_ctl -o "-k <相对路径>"` 必失败**：postgres 启动后 chdir 到 PGDATA，
  `PgEnv` 内路径一律转绝对
- **`pkill -f 'data/pgdata'` 会杀掉自己的 shell**（模式自匹配），换精确匹配
- 便携实例是**项目本地**的：不注册系统服务、不随开机自启，用 WebUI 前先 `aris db start`

### 依赖 / 环境
- **torch 与 torchvision 必须同锁 `pytorch-cpu` 源**：否则 torchvision 装成 CUDA wheel，
  报 `operator torchvision::nms does not exist`，`transformers` 直接导入失败
- **缓存与 HOME 必须收进 `data/`**：micromamba 用 `MAMBA_ROOT_PREFIX` /
  `CONDA_PKGS_DIRS` / `XDG_CACHE_HOME` / `HOME`，HF 模型用 `HF_HOME`
- **OpenVINO 遥测 warning 无害**：它往 `$HOME/intel` 写 consent 文件，
  `OV_TELEMETRY_OPT_OUT` 压不住（opt_in_checker 用 `Path.home()`），可忽略
- 只读 `~/.cache` 的环境下给 uv 加 `UV_CACHE_DIR=$PWD/data/.uv-cache`

### 打包 / 版本
- **uv 默认只按 `pyproject.toml` 判定项目元数据缓存**：版本号走 dynamic
  （从 `src/aris/__init__.py` 读）时，必须在 `[tool.uv] cache-keys` 里显式声明
  该文件，否则改了版本 `uv sync` / `uv lock` 也不会重建元数据，出现
  `aris --version` 与已安装的 `aris==X` 不一致（实测踩过，release-check 有对应检查）
- **版本号必须能被 setuptools 解析为 PEP 440**：`9.9.9-test` 会让构建直接抛
  `InvalidVersion`；bump 脚本只放行 `X.Y.Z`

### 命名 / 导入
- **函数与模块同名会被包重导出遮蔽**：`bootstrap()` 与 `bootstrap.py` 撞名后
  `store.bootstrap` 拿到的是函数（已连踩两次）→ 改名 `bootstrap_env`；
  测试里要模块对象用 `importlib.import_module("aris.store.bootstrap")`

### WebUI / 前端
- **HTML 转 markdown 别用 trafilatura**：它的 markdown 输出会抹平标题层级，
  用 BeautifulSoup 自写转换
- **Jinja 里 `job.items` 会解析成 dict 的 `.items` 方法**（`TypeError`）→ 用 `job["items"]`
- **「只刷新一次」的守门不能用 `sessionStorage`**：每次加载先清 → 判定完成 → 再 reload，
  死循环。终止条件放服务端（模板 `data-poll`）+ 终态 `location.replace()`
- **鉴权不能用前缀宽匹配**（`/loginfoo` 可绕过 `/login`）→ 精确集合 + 前缀分离
- **marked.js 输出必须过 DOMPurify**；SSE 事件流一律 `tojson` + 文本节点，不碰 `innerHTML`
- **CPU 密集的接口（本地 embedding 约 20s 加载）别写成 `async def`**：单 worker 下会
  卡住整站，用同步 `def`（走线程池）或后台任务

### 测试
- **别往全局迁移登记表塞测试用重名版本**：同进程后续所有迁移都会误判漂移；
  隔离用例显式传 `migrations=`；写真实库的测试要在 `finally` 里清理

### 外部服务
- **DeepSeek 带 tools 必须回传 `reasoning_content`**，否则 400
- **Bing 直连三件套缺一不可**：Firefox UA + 先访问首页取 cookie（MUID）+
  搜索 URL 带 `form=QBRE`；真实链接要解 `/ck/a` 的 `u=` base64
  （详见 `developDoc/WEB-SEARCH.md`；Playwright 方案已删除，勿再实现）

## 文档索引（按需阅读）

| 开发内容 | 必读文档 |
|---|---|
| LLM 接入 / `core` 模块 | `developDoc/API-CALL.md` |
| 配置文件体系（三源分工 / 收口原则） | `developDoc/CONFIG.md` |
| 跨模块通讯总线 CMCB（`core.bus` 服务/事件/审计） | `developDoc/CMCB.md` |
| 技能系统（`behavior.skills`） | `developDoc/SKILLS.md` |
| 联网搜索方案（演进历史 / 留档） | `developDoc/WEB-SEARCH.md` |
| `memory` 模块（Embedding / 检索） | `developDoc/EMBEDDING.md` |
| 知识库（独立 RAG 知识检索；议题全部定案） | `developDoc/KNOWLEDGE-BASE.md` |
| LLM 提供商/模型管理（list/check/fetch/退休） | `developDoc/LLM-PROVIDER-MGMT.md` |
| `voice` 模块（STT / TTS） | `developDoc/stt&&tts选型.md` |
| 插件系统（草案，含后续讨论） | `developDoc/PLUGIN.md` |
| WebUI 管理后台（审计/技能/提供商/插件） | `developDoc/WEBUI.md` |
| WebUI 安全审查与总线化改造（修复清单/计划/进度） | `developDoc/SECURITY-AND-REFACTOR-PLAN.md` |
| 项目蓝图 | `developDoc/Project-Aris.md` |
| 启动编排（`aris serve`：启动顺序 / 自启策略 / 失败分级） | `developDoc/SERVE.md` |
| 记忆架构总体（候选参考） | `referenceDocumentation/记忆数据库-bydsv4fpre.html`、`MemoryTips-bygemini.md` |
| 开发路线总体（候选参考） | `referenceDocumentation/总览-bydsv4fpre.html` |
| 开发进度（每次开发前先读） | `PROGRESS.md` |
| 后续待办（未排期的中长期方向） | `developDoc/BACKLOG.md` |
| 开发进度归档（历史条目与踩坑记录，查旧事用） | `developDoc/PROGRESS-ARCHIVE.md` |
