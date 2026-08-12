# Aris

拟人 AI「Aris」，参考 Neuro-sama，目标是「社会学意义上的人」：长期独立人格、
持续演进的世界观、人际关系网和成长轨迹。纯个人项目，但以可维护性为最高优先级，
目标运行数年。

## 快速开始

环境要求：Python >= 3.12，uv（主环境为 Arch Linux）。

```bash
# 1. 安装依赖并创建虚拟环境
uv sync

# 2. 准备环境变量（复制模板后按需填写，密钥只放 .env）
cp .env.example .env

# 3. 环境自检
aris doctor

# 4. 开始与 Aris 对话（交互循环）
aris chat
```

## CLI

| 命令 | 说明 |
|---|---|
| `aris doctor` | 环境自检（Python 版本、C 扩展、.env、数据目录） |
| `aris llm test` | 手动验证 LLM 连接（流式对话，调试 fallback） |
| `aris chat [消息]` | 文字对话：带消息走单次问答，不带进入交互循环 |

`aris chat` 常用选项：

- `--system <文本>`：自定义系统提示词（默认使用内置 Aris 人设）
- `--model <id>`：切换模型（默认 `deepseek-v4-flash-free`）
- `--thinking`：开启思考模式（默认关闭，首字响应更快）
- `--no-tools`：禁用工具调用（默认开启内置工具：联网搜索等）

交互循环内可用 `/help` 查看全部指令（`/new`、`/model`、`/clear`、`/quit` 等）。

## 配置体系

三个配置源各管一摊，详情见 `developDoc/CONFIG.md`：

| 配置源 | 管什么 |
|---|---|
| `.env`（`ARIS_` 前缀） | 启动级参数、密钥、`data_dir`、`llm_providers_file` |
| `config/providers.toml` | LLM 提供方（base_url / key 环境变量名 / 超时 / 传输 / 模型） |
| `config/*.toml` | 功能可调参数：chat / search / logging / audit / notify |

密钥一律只放 `.env`（不进 git）；`config/providers.example.toml` 为提供方模板。

## 模块结构

```
src/aris/
├── cli.py          # CLI 入口（子命令式）
├── config.py       # 全局配置（pydantic-settings，ARIS_ 前缀）
├── logging.py      # loguru 统一日志
├── cfgtoml.py      # 模块级 toml 配置加载器（零依赖）
├── core/           # 基础设施：统一通讯层（bus）+ LLM 提供方抽象
│   ├── bus.py      #   服务注册表 + 事件总线 + 审计
│   └── llm/        #   提供方抽象 / fallback / 流式 / 工具调用
├── persona/        # 人格（提示词工程起步）：system_prompt 服务
├── behavior/       # 行为：agent loop + 工具注册表 + 内置工具
│   ├── tools/      #   内置工具：web_search（Tavily）、web_open、get_current_time
│   └── skills/     #   skill 技能系统：目录化、按需激活（demo：note 备忘）
├── chat/           # 文字对话：session（会话）+ tui（全屏界面）+ commands（指令）
├── memory/         # 记忆系统（Embedding + 数据库，占位）
├── voice/          # 语音 STT / TTS（占位）
└── csrc/           # C 扩展（ctypes 按需加载，可选编译）

config/             # 配置文件（见上表）
data/               # 运行时数据（日志等），不进 git
developDoc/         # 模块级开发文档
referenceDocumentation/  # 候选参考文档
```

模块间通讯统一经 `core.call` / `core.provide`（统一通讯层），架构见
`developDoc/BUS-ARCHITECTURE.md`。

## 数据与备份

- 运行时数据（日志、数据库文件等）统一放 `data/`，**不进 git**
- 备份建议：定期 `rsync -av data/ /backup/aris-data/`；将来用 PostgreSQL 时用 `pg_dump`
- 密钥（API key）一律放 `.env`，同样不进 git

## 文档索引

| 文档 | 内容 |
|---|---|
| `AGENTS.md` | 项目通用要求、编码约定、已定案决策（唯一权威） |
| `PROGRESS.md` | 开发进度、已知问题、下一步（每次开发前先读） |
| `developDoc/Project-Aris.md` | 项目蓝图 |
| `developDoc/API-CALL.md` | LLM 接入与 core 模块 |
| `developDoc/CONFIG.md` | 配置体系 |
| `developDoc/BUS-ARCHITECTURE.md` | 统一通讯层 |
| `developDoc/WEB-SEARCH.md` | 联网搜索方案 |
| `developDoc/EMBEDDING.md` | 记忆 / Embedding 方案 |
| `developDoc/stt&&tts选型.md` | 语音选型 |
| `referenceDocumentation/` | 候选参考文档 |
