# Project-Aris 项目规划与决策

本文档记录项目立项以来的关键决策，是开发的权威依据。编码相关要求见 [CODING-GUIDELINES.md](./CODING-GUIDELINES.md)。

## 项目定位

- 拟人 AI「Aris」，参考 Neuro-sama，目标是「社会学意义上的人」：长期独立人格、持续演进的世界观、人际关系网和成长轨迹
- 纯个人项目，但可维护性为最高优先级，目标运行数年

## 开发环境

- **主开发环境**：Linux 桌面（Wayland）
- **次环境**：Termux（安卓），代码需兼顾两边能跑

## 技术栈决策

| 项目 | 决策 | 说明 |
|---|---|---|
| 编程语言 | Python 为主 | C 语言辅助（性能敏感处），必要时 TypeScript |
| Python 版本 | 开发按 3.14，最低支持 3.12 | 尽量用新特性 |
| 依赖管理 | uv | 锁文件，Termux 可用 |
| 配置系统 | pydantic-settings 优先，按环境分级 | `.env` + 环境变量，API key 一律放 env；备选方案见下方「配置系统方案」 |
| 日志 | loguru | 统一日志方案 |
| 包布局 | src 布局 | 包名 `aris`，`src/aris/` |
| 测试 | pytest（待确认） | 骨架阶段暂不强制 |

## 配置系统方案（2026-08，待定）

背景：Termux（aarch64-android，Python 3.14）无 pydantic-core 预编译 wheel，源码构建
需 Rust（不可行），Termux 仓库亦无 python-pydantic 包（已实测）→ pydantic-settings
在 Termux 无法安装。按环境分级：

1. **第一选择**：pydantic-settings（PC / Linux 桌面可装时）
2. **第二选择**：标准库实现（dataclass + 手写 .env 解析，约 30 行，零依赖，两平台通吃）
3. **最后备选（野路子）**：C 语言模拟配置解析（ctypes 接入，不推荐：文本解析用 C
   违背 KISS，增加编译依赖，可维护性差）

定案方式：用户到 PC 上实测 pydantic-settings 可装性后决定；在此之前 config.py
保持现状不重写。

## 模块划分（对应 Project-Aris.md）

- `core/` —— Agent 核心、LLM 连接（提供方抽象）
- `memory/` —— 记忆系统：Embedding + 数据库
- `voice/` —— STT（语音识别）、TTS（语音合成）
- `persona/` —— **已搁置**：人格系统，实现方式未定（提示词工程 vs 现有 MCP），待用户想清楚再建
- `behavior/` —— 行为：函数调用、MCP 服务器、Skills、插件

## 关键技术选型

- **LLM**：暂定，接口鱼龙混杂，等调研后再定；API key 由用户填 env
- **记忆数据库**：PostgreSQL + pgvector 起步，之后再加 GraphRAG（Apache AGE 或递归 CTE）
- **Embedding**：本地优先（Bekko-embedding-v1-a25m，待用户实测 CPU 占用确认），云端备选 Cloudflare Workers AI BGE-M3；提供方抽象可插拔，**每次会话启动时向用户确认当前方案**
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

- [ ] 配置系统方案（用户 PC 实测 pydantic-settings 可装性后定，见上节）
- [ ] Python 静态检查/格式化工具选型（ruff 为 Rust 二进制，Termux 大概率装不上；备选纯 Python 的 black+isort+flake8）
- [ ] LLM 提供方选型（用户调研中）
- [ ] STT 选型
- [ ] Embedding 本地模型实测（CPU 占用是否可接受，决定本地优先还是 Cloudflare 优先）
- [ ] 人格系统实现方式（提示词工程 vs 现有 MCP，决定是否重建 persona 模块）
- [ ] 测试框架是否启用 pytest
