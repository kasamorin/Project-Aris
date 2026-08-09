# Project-Aris 项目规划与决策

本文档记录项目立项以来的关键决策，是开发的权威依据。编码相关要求见 [AGENTS.md](./AGENTS.md)。

## 项目定位

- 拟人 AI「Aris」，参考 Neuro-sama，目标是「社会学意义上的人」：长期独立人格、持续演进的世界观、人际关系网和成长轨迹
- 纯个人项目，但可维护性为最高优先级，目标运行数年

## 开发环境

- **主开发环境**：Arch Linux（Wayland 桌面）——默认开发环境
- **次环境**：Termux（安卓），仅用于没有电脑时改文档，不运行代码

## 技术栈决策

| 项目 | 决策 | 说明 |
|---|---|---|
| 编程语言 | Python 为主 | C 语言辅助（性能敏感处），必要时 TypeScript |
| Python 版本 | 开发按 3.14，最低支持 3.12 | 尽量用新特性 |
| 依赖管理 | uv | 锁文件，Termux 可用 |
| 配置系统 | pydantic-settings（已定案） | `.env` + 环境变量，API key 一律放 env；Termux 暂不可装，见下方「配置系统方案」 |
| 日志 | loguru | 统一日志方案 |
| 包布局 | src 布局 | 包名 `aris`，`src/aris/` |
| 测试 | pytest（待确认） | 骨架阶段暂不强制 |

## 配置系统方案（2026-08，已定案）

背景：Termux（aarch64-android，Python 3.14）无 pydantic-core 预编译 wheel，源码构建
需 Rust（不可行），Termux 仓库亦无 python-pydantic 包（已实测）→ pydantic-settings
在 Termux 无法安装。分级方案：

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

## 模块划分（对应 Project-Aris.md）

- `core/` —— 基础设施：Agent 核心 + 一切外部基础连接（LLM API 等）的统一出入口（提供方抽象）
- `memory/` —— 记忆系统：Embedding + 数据库
- `voice/` —— STT（语音识别）、TTS（语音合成）
- `persona/` —— **已搁置**：人格系统，实现方式未定（提示词工程 vs MCP），待用户想清楚再建
- `behavior/` —— 行为：函数调用、连接外部 / 自建 MCP 服务器、Skills
- 对话 CLI：单独分出来实现（如 `aris chat`），连接仍走 `core/`
- 插件系统：**后续可能增加**——MCP 服务器可做同样的事，届时再评估是否独立成模块

## 关键技术选型

- **LLM**：提供方式与提供方**未定**（候选 v1/chat、v1/responses、Anthropic 格式等；
  可能多个提供方、多个模型做 fallback），等调研后再定；API key 由用户填 env
- **记忆数据库**：PostgreSQL + pgvector 起步，之后再加 GraphRAG（Apache AGE 或递归 CTE）；
  表结构预留宽松，方便以后加图谱
- **记忆实现方式**：走 RAG，但不用 LangChain/LlamaIndex 等现有框架（自研轻量实现）
- **Embedding**：**已定案（2026-08-09）**：按记忆层级分 provider——
  热记忆本地 Bekko-embedding-v1-a25m（OpenVINO CPU，实测日常 CPU 5.3% / 延迟 10ms /
  内存 1.5GiB）；冷记忆云端 Cloudflare Workers AI BGE-M3（免费额度内近零成本，
  高负荷归档上云省本机算力）。两库维度不同（384/1024），各建独立 pgvector 表，
  详见 `referenceDocumentation/EMBEDDING.md`
- **联网搜索（基本定案）**：Google & Bing 优先、Tavily 备选；实现方式未定
  （大概模拟真实浏览器），实现 behavior 模块时再定
- **TTS**：Edge TTS 起步（免费），Azure TTS 备选
- **STT**：暂未定（参考候选：Groq Whisper / 通义听悟）
- **交互形态**：先文字对话，后加语音

## 开发路线（第一步）

1. **搭标准项目骨架**（轻量）：目录结构 + 配置系统 + 日志 + CLI 入口，各模块留占位
   - 骨架文件已完成（2026-08）；`uv sync` 在 Termux 被 pydantic-core 阻塞，
     等配置系统方案定案后执行（见上节）
2. 接入 LLM（等选型确定）
3. 跑通文字对话
4. 记忆系统（PostgreSQL + pgvector）
5. 人格系统 —— **搁置**，实现方式未定（提示词工程 vs MCP）
6. 语音链路（STT → LLM → TTS）
7. 行为扩展（函数调用 / MCP / Skills / 插件）
8. GraphRAG

## 待定事项

- [ ] Python 静态检查/格式化工具选型（候选：ruff / black+isort+flake8）
- [ ] LLM 提供方式与提供方选型（v1/chat vs v1/responses vs Anthropic 格式等；
      可能多提供方、多模型做 fallback，用户调研中）
- [ ] 记忆架构（三层记忆模型：感觉/短期/长期，含反思、遗忘权重、时间线冲突处理，
      用户构想中、未完善，以后可能换）
- [ ] STT 选型
- [x] Embedding 本地模型实测（2026-08-09 完成：Bekko a25m 日常 CPU 5.3% / 延迟 10ms /
      内存 1.5GiB；定案按记忆层级分 provider，热记忆本地、冷记忆 Cloudflare BGE-M3）
- [ ] 人格系统实现方式（提示词工程 vs MCP，决定是否重建 persona 模块）
- [ ] 测试框架是否启用 pytest
