# 开发进度报告

更新于：2026-08-09（Arch Linux 会话）

## 已完成

- **LLM 连接层（2026-08-09）**：`core/llm` 模块落地并跑通流式对话。
  - LLM 选型定案：多提供方抽象 + fallback，本次实现 OpenAI Chat Completions 格式
  - 统一请求模板（Message / ChatRequest）+ formatters 按 format 翻译请求体
  - 双传输：openai SDK（默认） + httpx 手写（SSE），从一开始就流式（TTS 增量需要）
  - fallback：报错即切下家；总体超时预算（默认 30s，含切换耗时）耗尽则进错误处理
  - 错误处理：不暴露原始报错，返回预设提示语 + 错误广播（桌面弹窗 + 推送注册接口）
  - 配置：`providers.toml`（toml 定义 provider/模型结构，不进 git）+ `.env` 放密钥
  - 验证：`aris llm test` 子命令流式实测；本地 mock 验证 sdk/httpx/fallback/超时四链路
  - **bug 修复**：pydantic-settings 读 .env 不注入 os.environ，`transport._api_key`
    改为经 `config._load_env_into_environ()` 同步后再读，CLI 跑通
- **OpenCode Zen 免费模型接入（2026-08-09）**：8 个免费模型（`*-free`、`big-pickle`）
  全部走 `/chat/completions`（已实测 + `/models` 接口核实），加入 `providers.toml`
- **Embedding 定案（2026-08-09）**：热记忆本地 Bekko a25m（OpenVINO CPU），冷记忆
  云端 Cloudflare BGE-M3；两库维度不同（384/1024）各建独立 pgvector 表。详见
  `developDoc/EMBEDDING.md`
- 骨架 v0.1.0：pyproject.toml（uv + src 布局）、.env.example、README.md、.gitignore
- 配置系统定案：pydantic-settings（Arch 上 `uv sync` 跑通）
- 文档：AGENTS.md、开发文档拆分、参考文档同步

## 当前阻塞

- 无

## 待定决策

- 记忆架构（三层记忆模型，构想中、未完善，可能换）
- STT 选型
- persona 实现方式（提示词工程 vs MCP，模块已搁置）
- Python 静态检查/格式化工具（ruff vs black+isort+flake8）
- 测试框架是否启用 pytest

## 下一步

1. 跑通文字对话（CLI 交互循环，基于 core/llm）
2. 记忆系统（PostgreSQL + pgvector）
3. 语音链路（STT → LLM → TTS）
4. 行为扩展（函数调用 / MCP 服务器 / Skills）

## 专项优化（暂缓）

- **/models 动态获取模型名**：`GET {base_url}/models` 返回 `data[].id`，
  opencode 用静态目录（Models.dev）不从该接口动态拉；Aris 后续可加
  `fetch_models()` 免手填 providers.toml 模型名（`aris llm test --list-models`）
