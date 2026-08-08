# AGENTS.md

## 环境警告（最重要）

- 本环境（Termux）的 bash 工具**可能**卡死（超时 120s 无输出）。
- 允许执行 bash，但规则：会话开始时（判断环境为 Termux 时）先执行一次简单命令（如 `echo ok`）测试 bash 是否可用。
- 只要任意一个 bash 命令能正常返回不超时，即可自由按需执行（包括 git）。
- 若测试命令超时/卡死，则视为 bash 不可用：避免用 bash，尤其禁止 git 命令；需要提交时把命令与提交信息写好交给用户手动执行。
- 文件操作优先用 read/write/edit/glob 工具；glob 偶发失败时改用 read 目录。

## 会话启动检查（每次开始工作前）

- **Embedding 方案确认**：先问用户当前用「本地模型」还是「Cloudflare BGE-M3」，
  结果影响 memory 模块设计。用户未确认前不实现任何 Embedding 连接。

## 现状

- 骨架已搭（2026-08）：pyproject.toml + src/aris/（config/logging/cli + 模块占位 + csrc）。
  `uv sync` 在 Termux 被 pydantic-core 阻塞（无 wheel、需 Rust），配置系统方案待定。
- 下一步：配置系统定案 → uv sync 跑通 → 接入 LLM（等选型确定）。
- 人格模块（persona）已搁置：实现方式未定（提示词工程 vs MCP）。
- 状态权威来源：
  - `CODING-GUIDELINES.md` —— 编码原则与哲学（必须遵守）
  - `PROJECT-PLAN.md` —— 技术决策、模块划分、路线图、待定事项
  - `PROGRESS.md` —— 开发进度报告（当前阻塞、待定决策、下一步）
  - `referenceDocumentation/` —— 参考文档（记忆架构、语音选型、开发总览）

## 编码约定（摘要，详见 CODING-GUIDELINES.md）

- 标识符英文，注释中文
- Git 提交：Conventional Commits 前缀 + 中文内容（如 `feat: 添加登录功能`）
- KISS：一个东西只做一件事
- 遇到歧义/不确定需求：先问用户，不擅自假设

## 技术栈（已定，勿自行更改）

- Python：最低 3.12，开发按 3.14
- 依赖管理：uv；包布局 src 布局，包名 `aris`
- 配置：pydantic-settings 优先，**方案待定**（Termux 无法安装 pydantic-core，分级备选见 PROJECT-PLAN.md「配置系统方案」；未定案前不改 config.py）
- 日志：loguru；测试：pytest（待确认）

## 待定（勿替用户做决定）

- 配置系统方案（PC 实测 pydantic-settings 可装性后定，见 PROJECT-PLAN.md）
- LLM 提供方：用户正在调研选型，**不要接入/实现任何 LLM 连接**，直到用户确定
- Embedding 方案：本地（Bekko）vs Cloudflare BGE-M3，会话启动时确认；本地待用户实测 CPU 占用
- STT 选型、人格系统实现方式（提示词工程 vs MCP，persona 模块已搁置）
- 记忆库（计划 PostgreSQL + pgvector，后加 GraphRAG）
