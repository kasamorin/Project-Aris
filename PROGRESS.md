# 开发进度报告

更新于：2026-08-08（Termux 会话）

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

## 当前阻塞

- [ ] 依赖安装：Termux（aarch64-android，Python 3.14）无 pydantic-core 预编译 wheel，
      源码构建需 Rust（不可行）；Termux 仓库无 python-pydantic（已实测）
- [ ] 配置系统方案待定：分级备选 = pydantic-settings（PC 可装时）→ 标准库实现 →
      C 模拟（最后备选，不推荐），等用户 PC 实测后定案

## 待定决策

- 配置系统实现（等 PC 实测 pydantic-settings 可装性后定）
- LLM 提供方（用户调研中）
- STT 选型
- Embedding 本地实测（CPU 占用是否可接受）
- persona 实现方式（提示词工程 vs MCP，模块已搁置）

## 下一步

1. 配置系统定案（PC 实测 pydantic-settings）
2. uv sync + aris doctor 跑通
3. 接入 LLM（等选型确定）
