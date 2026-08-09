# 开发进度报告

更新于：2026-08-09（Arch Linux 会话）

## 已完成

- 骨架 v0.1.0：pyproject.toml（uv + src 布局）、.env.example、README.md、.gitignore
- src/aris/：cli.py（doctor 子命令）、config.py（pydantic-settings）、logging.py（loguru）、
  模块占位（core / memory / voice / behavior，无 persona）、csrc（demo.c + ctypes 加载）
- 文档：PROJECT-PLAN.md（Embedding 本地优先 + Cloudflare 备选、persona 搁置、
  配置系统分级方案）、AGENTS.md（会话启动确认 Embedding 方案）、参考文档同步
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

- [ ] LLM 提供方选型中（用户调研中），选型确定前不实现 LLM 连接

## 待定决策

- LLM 提供方（用户调研中）
- STT 选型
- Embedding 本地实测（CPU 占用是否可接受；当前按「未定」处理）
- persona 实现方式（提示词工程 vs MCP，模块已搁置）
- Python 静态检查/格式化工具（ruff vs black+isort+flake8）
- 测试框架是否启用 pytest

## 下一步

1. 接入 LLM（等选型确定）
2. 跑通文字对话
3. 记忆系统（PostgreSQL + pgvector）
