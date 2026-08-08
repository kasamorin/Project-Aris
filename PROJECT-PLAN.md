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
| 配置系统 | pydantic-settings 优先 | `.env` + 环境变量，API key 一律放 env；不行再用标准库方案 |
| 日志 | loguru | 统一日志方案 |
| 包布局 | src 布局 | 包名 `aris`，`src/aris/` |
| 测试 | pytest（待确认） | 骨架阶段暂不强制 |

## 模块划分（对应 Project-Aris.md）

- `core/` —— Agent 核心、LLM 连接（提供方抽象）
- `memory/` —— 记忆系统：Embedding + 数据库
- `voice/` —— STT（语音识别）、TTS（语音合成）
- `persona/` —— 人格系统：提示词工程等
- `behavior/` —— 行为：函数调用、MCP 服务器、Skills、插件

## 关键技术选型

- **LLM**：暂定，接口鱼龙混杂，等调研后再定；API key 由用户填 env
- **记忆数据库**：PostgreSQL + pgvector 起步，之后再加 GraphRAG（Apache AGE 或递归 CTE）
- **Embedding**：预计本地部署 Bekko-embedding-v1-a25m（待定）
- **TTS**：Edge TTS 起步（免费），Azure TTS 备选
- **STT**：暂未定（参考候选：Groq Whisper / 通义听悟）
- **交互形态**：先文字对话，后加语音

## 开发路线（第一步）

1. **搭标准项目骨架**（轻量）：目录结构 + 配置系统 + 日志 + CLI 入口，各模块留占位
   - 待办：Termux 的 bash 环境问题解决后再动手
2. 接入 LLM（等选型确定）
3. 跑通文字对话
4. 记忆系统（PostgreSQL + pgvector）
5. 人格系统
6. 语音链路（STT → LLM → TTS）
7. 行为扩展（函数调用 / MCP / Skills / 插件）
8. GraphRAG

## 待定事项

- [ ] LLM 提供方选型（用户调研中）
- [ ] STT 选型
- [ ] Embedding 模型确认
- [ ] 测试框架是否启用 pytest
