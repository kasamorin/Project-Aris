# 开发进度报告

更新于：2026-08-08（Termux 会话）

## 已完成

- 骨架 v0.1.0：pyproject.toml（uv + src 布局）、.env.example、README.md、.gitignore
- src/aris/：cli.py（doctor 子命令）、config.py（pydantic-settings）、logging.py（loguru）、
  模块占位（core / memory / voice / behavior，无 persona）、csrc（demo.c + ctypes 加载）
- 文档：PROJECT-PLAN.md（Embedding 本地优先 + Cloudflare 备选、persona 搁置）、
  AGENTS.md（会话启动确认 Embedding 方案）、参考文档同步
- git 首次提交 aedd66b「feat: 搭建 aris 项目骨架」

## 当前阻塞

- [ ] 依赖安装：Termux（aarch64-android，Python 3.14）无 pydantic-core 预编译 wheel，
      源码构建需 Rust（不可行）；Termux 仓库无 python-pydantic（已实测）
- [ ] 配置系统方案待定：标准库实现 / PC 端 pydantic-settings / C 模拟（不推荐）
- [ ] C 扩展未编译（cc 命令待重试，此前输入有误）
- [ ] 清理：src/aris.egg-info/ 误提交进 git，待 `git rm -r --cached` + .gitignore 已补 *.egg-info/

## 待定决策

- 配置系统实现（等 PC 实测 pydantic-settings 可装性后定）
- LLM 提供方（用户调研中）
- STT 选型
- Embedding 本地实测（CPU 占用是否可接受）
- persona 实现方式（提示词工程 vs MCP，模块已搁置）

## 下一步

1. 配置系统定案
2. 清理 egg-info（git rm --cached）
3. uv sync + aris doctor 跑通
4. PC 上验证 pydantic-settings 可装性
