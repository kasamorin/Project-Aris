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

## 现状

- 骨架 v0.1.0 完成（uv + src 布局、pydantic-settings 配置、loguru 日志、CLI、
  模块占位、C 扩展 demo）；配置系统已定案并在 Arch 跑通 `uv sync`。
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
- **版本与 tag**：`pyproject.toml` 为唯一版本源，`src/aris/__init__.py`
  同步 `__version__`。版本发布时：develop 上 bump 版本 → 合并回 main →
  打 `vX.Y.Z` tag → `git push --tags`。
- **保留分支**：`oldWish` 为历史保留分支（main 祖先：首次提交/README/许可证），
  **不要删除**，也不建议在此分支上继续开发。

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

- `core/` —— 基础设施：统一通讯层（`bus.py` 服务注册表 + 事件总线 + 审计）+
  LLM 提供方抽象（多提供方 fallback、流式、工具调用）
- `memory/` —— 记忆系统：Embedding + 数据库
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
- 插件系统：**后续可能增加**——MCP 服务器可做同样的事，
  届时再评估是否独立成模块

### 模块间调用规则（统一通讯层，2026-08-12 定案）

- 模块间通讯**一律走 `core.call` / `core.provide`**，不直接跨模块 import 调用
- 核心类实例自注册（`__init__` 里 `provide` 自己的方法），命名 `module.service`
- 明确不走总线的边界：对象构造/装配（依赖注入）、同模块内部调用、纯类型引用
  （如 Message）；CLI 组装根可保持直接引用
- 服务表与架构详见 `developDoc/BUS-ARCHITECTURE.md`

## 开发路线

> **当前聚焦：WebUI 管理后台**（设计定稿 v2，2026-08-22，实现待启动，
> 详见 `developDoc/WEBUI.md`）。前置决策审查已完成，8 项待定已记录，
> 编码前须逐一定案。

1. **搭标准项目骨架**（轻量）：目录结构 + 配置系统 + 日志 + CLI 入口，各模块留占位
   - 骨架已完成（2026-08），配置系统已定案并跑通 `uv sync`（2026-08-09）
2. 接入 LLM —— **已完成**（2026-08-09，`core/llm`，见 PROGRESS.md）
3. 跑通文字对话 —— **已完成**（2026-08-09，`aris chat`，见 PROGRESS.md）
4. 记忆系统（PostgreSQL + pgvector）
5. 人格系统 —— **提示词工程起步，已完成简单版**（2026-08-12，`persona/`）；
   世界观/人际关系/成长轨迹后续演进
6. 语音链路（STT → LLM → TTS）
7. 行为扩展（函数调用 / MCP 服务器 / Skills）—— **函数调用已完成**（2026-08-09），
   MCP / Skills 待后续；联网搜索已完成（Tavily 唯一主链路 + web_open）
8. GraphRAG

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
- ~~测试框架是否启用 pytest~~（已定：2026-08-18 启用 pytest，见技术栈）

## 文档索引（按需阅读）

| 开发内容 | 必读文档 |
|---|---|
| LLM 接入 / `core` 模块 | `developDoc/API-CALL.md` |
| 配置文件体系（三源分工 / 收口原则） | `developDoc/CONFIG.md` |
| 统一通讯层（`core.bus` 服务/事件/审计） | `developDoc/BUS-ARCHITECTURE.md` |
| 技能系统（`behavior.skills`） | `developDoc/SKILLS.md` |
| 联网搜索方案（演进历史 / 留档） | `developDoc/WEB-SEARCH.md` |
| `memory` 模块（Embedding / 检索） | `developDoc/EMBEDDING.md` |
| LLM 提供商/模型管理（list/check/fetch/退休） | `developDoc/LLM-PROVIDER-MGMT.md` |
| `voice` 模块（STT / TTS） | `developDoc/stt&&tts选型.md` |
| 插件系统（草案，含后续讨论） | `developDoc/PLUGIN.md` |
| WebUI 管理后台（审计/技能/提供商/插件） | `developDoc/WEBUI.md` |
| 项目蓝图 | `developDoc/Project-Aris.md` |
| 记忆架构总体（候选参考） | `referenceDocumentation/记忆数据库-bydsv4fpre.html`、`MemoryTips-bygemini.md` |
| 开发路线总体（候选参考） | `referenceDocumentation/总览-bydsv4fpre.html` |
| 开发进度（每次开发前先读） | `PROGRESS.md` |
