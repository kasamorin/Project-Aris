# 开发进度报告

更新于：2026-08-09（Arch Linux 会话）

## 已完成

- **Embedding 定案（2026-08-09）**：按记忆层级分 provider——
  热记忆本地 Bekko-embedding-v1-a25m（OpenVINO CPU），冷记忆云端 Cloudflare BGE-M3。
  本地实测：日常稀疏检索（每 3s 一条）平均 CPU 5.3%、单条延迟 10.4ms、内存 1.5GiB；
  连续压力 60s 约 1164%（约 12 核满载，对应冷记忆批量归档这类高负荷任务，上云承担）。
  Cloudflare BGE-M3 免费额度每天 10,000 Neurons（embedding 每次 1-5 Neurons，
  个人项目近零成本）；两库维度不同（384/1024）各建独立 pgvector 表。
  调用细节与抽象设计见 `developDoc/EMBEDDING.md`。
- 骨架 v0.1.0：pyproject.toml（uv + src 布局）、.env.example、README.md、.gitignore
- src/aris/：cli.py（doctor 子命令）、config.py（pydantic-settings）、logging.py（loguru）、
  模块占位（core / memory / voice / behavior，无 persona）、csrc（demo.c + ctypes 加载）
- 文档：AGENTS.md（已定案：Embedding 分层方案、persona 搁置、配置系统分级方案、
  编码规范等）、参考文档同步
- 编码规范定案：行宽 100、类型标注尽量多、docstring 中文、C 命名规范
  （函数大驼峰/变量小驼峰/指针 *p）、Git 完整格式（head+body）、feature 分支、
  .clang-format 配置（已提交）
- git：aedd66b「feat: 搭建 aris 项目骨架」、03c119b「docs: 添加进度报告并清理构建产物」、
  b832bdb「docs: 更新配置分级方案与编码规范，统一 C 命名」
- egg-info 误提交已清理（.gitignore 已补 *.egg-info/）
- C 扩展 demo.so 编译成功（cc 无报错；函数名 ArisDemoAdd 已同步重编译）
- **配置系统定案（2026-08-09，Arch Linux）**：pydantic-settings。Arch 上
  `uv sync` 跑通（pydantic-settings 2.15.0 / pydantic 2.13.4 / Python 3.14.6），
  `aris doctor` 自检通过

## 当前阻塞

- [ ] LLM 提供方式与提供方选型中（用户调研中；候选 v1/chat、v1/responses、Anthropic
  格式等，可能多提供方、多模型 fallback），选型确定前不实现 LLM 连接

## 待定决策

- LLM 提供方式与提供方（用户调研中）
- 记忆架构（三层记忆模型，构想中、未完善，可能换）
- STT 选型
- persona 实现方式（提示词工程 vs MCP，模块已搁置）
- Python 静态检查/格式化工具（ruff vs black+isort+flake8）
- 测试框架是否启用 pytest

## 下一步

1. 接入 LLM（等选型确定）
2. 跑通文字对话
3. 记忆系统（PostgreSQL + pgvector）
