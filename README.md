# Aris

拟人 AI「Aris」，参考 Neuro-sama，目标是「社会学意义上的人」：长期独立人格、
持续演进的世界观、人际关系网和成长轨迹。纯个人项目，但以可维护性为最高优先级，
目标运行数年。

## 快速开始

环境要求：Python >= 3.12，uv（Termux 与 Linux 均可）。

```bash
# 1. 安装依赖并创建虚拟环境
uv sync

# 2. 准备环境变量（可选，默认值可直接用）
cp .env.example .env

# 3. 环境自检
aris doctor

# 4. 无参数运行查看帮助
aris
```

## 可选：编译 C 扩展

```bash
cc -shared -fPIC -O2 -o src/aris/csrc/demo.so src/aris/csrc/demo.c
```

未编译也能正常运行，C 部分自动降级为 Python 实现。

## 目录结构

```
src/aris/
├── cli.py        # CLI 入口（子命令式）
├── config.py     # 全局配置（ARIS_ 前缀，.env 读取；实现方案见 PROJECT-PLAN.md）
├── logging.py    # loguru 统一日志
├── csrc/         # C 扩展（ctypes 按需加载）
├── core/         # Agent 核心 + LLM 连接（提供方抽象，占位）
├── memory/       # 记忆系统（Embedding + PostgreSQL/pgvector，占位）
├── voice/        # 语音 STT/TTS（占位）
└── behavior/     # 行为：函数调用 / MCP / Skills / 插件（占位）
```

## 数据与备份

- 运行时数据（日志、数据库文件等）统一放在 `data/`，**不进 git**。
- 备份建议：定期复制 `data/` 到外部介质，例如
  `rsync -av data/ /backup/aris-data/`（Termux / Linux 均可用）。
- 将来记忆库为 PostgreSQL 时，备份命令为 `pg_dump`，届时补充到本文档。
- 密钥（API key）一律放 `.env`，同样不进 git。

## 决策记录

技术决策与待定事项见 `PROJECT-PLAN.md`，编码规范见 `CODING-GUIDELINES.md`。
