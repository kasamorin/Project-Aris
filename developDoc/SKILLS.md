# Aris 技能（Skill）系统

> 2026-08-12 定案并落地（机制 + note demo 验证）。本文档是**唯一权威说明**，
> 后续改 skill 机制或新增 skill 时，须同步更新本文件。

## 目标与由来

项目待办清单（`../Project-Aris-Reference/todolist.txt`）第 1 项是 Skills、
第 4 项是接入 AstrBook（AI Agent 论坛），二者共同催生了本系统：
给 Aris 一个**目录化、按需加载**的能力扩展机制，skill 成为
后续一切外部能力（AstrBook 论坛、知识库、日记等）的统一挂载点。

## 形态：目录化 skill（定案）

每个 skill 是一个目录，存放在 `src/aris/behavior/skills/<name>/`：

```
skills/<name>/
├── SKILL.md        # frontmatter（name/description）+ 使用手册（模型要读的正文）
├── tools.py        # 可选：注册工具（须导出 register(registry) 函数）
└── references/     # 可选：详细文档/资源（三级渐进披露预留，后续启用）
```

- **动态按需加载**：不 import、不注册工具，直到模型激活该 skill。
- **激活幂等**：已激活的 skill 重复激活只返回正文，不重复注册工具。
- **机制 + demo 验证**：附 `note`（备忘）skill 作参考实现与真实验证载体。

## 三层渐进式披露（解决「长正文占 token」）

参考 Anthropic 官方 skill 指南与 Hermes 的分级装载模式，采用三层：

| 层级 | 内容 | 何时获取 | 成本 |
|---|---|---|---|
| L1 菜单 | 各 skill 的 name + description（frontmatter） | 会话构造时注入 system prompt | 极低（只读前端） |
| L2 激活 | 目标 SKILL.md 正文 + 装载 tools.py 工具 | 模型调 `activate_skill(name)` | 中（正文一次注入） |
| L3 详情 | references/ 等按路径读取 | 需要时再读（预留） | 按需 |

**关键约束：SKILL.md 正文本身必须短**（参考 Anthropic 建议，控制在
**500 行 / 5000 token 以内**）。正文只写「主流程 + 路由 + 注意事项」，
不含大段细节——细节拆到 `references/`，激活返回**整篇正文不截断**（正文短
所以无需截断）。references 读取工具待有长文档需求的 skill（如 AstrBook）时
再实现，YAGNI。

## 机制流程

1. 会话构造（`chat/session.py`）：若启用工具，创建 `SkillManager(registry)`，
   把 `activate_skill` 注册进 registry，并把技能菜单（`skills.menu` 服务）
   追加进 system prompt。
2. 模型看到菜单 + `activate_skill` 工具，判断需要某能力 → 调用
   `activate_skill("note")`。
3. `SkillManager.activate`：加载 `skills/note/tools.py`（若有 register 函数，
   注册其中工具）、返回 SKILL.md 全文（JSON 形式）。
4. 后续 agent loop 请求自动携带新工具定义；skill 工具执行失败由
   registry 统一宽容降级。

## 代码位置

| 文件 | 职责 |
|---|---|
| `src/aris/behavior/skills/__init__.py` | 导出 `SkillManager` |
| `src/aris/behavior/skills/manager.py` | 扫描、菜单、激活、加载工具 |
| `src/aris/behavior/skills/frontmatter.py` | SKILL.md frontmatter 简易解析（name/description） |
| `src/aris/behavior/skills/note/` | demo skill：备忘（SKILL.md + tools.py） |

`skills.menu` 服务注册于 `SkillManager.__init__`（与 `persona.system_prompt`
类似的模块级总线服务），`activate_skill` 是注册在 `ToolRegistry` 里的普通工具
（经 `tools.execute` 总线执行）。

## 如何写一个 skill

1. 建目录 `skills/<name>/`。
2. 写 `SKILL.md`：
   - frontmatter：`name`（英文标识）+ `description`（一两句中文，说明何时启用，
     会被注入菜单，**模型靠它判断何时激活**，务必写清触发场景）。
   - 正文：使用手册。告诉模型该技能能做什么、各工具何时用、有什么注意事项。
     保持简短（<500 行）。
3. 可选 `tools.py`：写各工具的实现，导出 `register(registry)`，在里面调用
   `registry.register(name, description=, parameters=, fn=)`。
   - 工具命名建议带技能前缀（如 `note_save`），避免与其他 skill 工具冲突。
   - 数据写到 `<data_dir>/` 下（日志/数据不进 git）。
4. 重启会话即被 `SkillManager` 发现（无需注册）。

## demo：note 备忘技能

- `note_save(title, content)`：保存/更新笔记（标题唯一，覆盖式），存于
  `<data_dir>/notes/*.txt`。
- `note_read(title)`：读取一条笔记。
- `note_list()`：列出全部笔记。
- 用途：验证「菜单注入 → 激活 → 工具可用 → 持久化落盘」全链路。
  开发者接手 AstrBook skill 时以此作模板。

## 外部 skill 兼容性（2026-08-14 实测 anthropics/skills）

下载 Anthropic 官方 skill 仓库（`github.com/anthropics/skills`）实测验证，两个
纯指令型 skill 已装入：`frontend-design`（UI 设计指南）、`doc-coauthoring`
（文档协作工作流），均为 Apache 2.0，LICENSE 随目录保留。结论：

- **frontmatter 完全兼容**：Anthropic 的 `name`/`description` 格式与我们的解析器
  一致；额外的 `license` 等字段被宽容忽略，不报错。
- **纯指令型 skill 开箱即用**：只含 SKILL.md（无 scripts/）的 skill，激活后模型
  直接按手册干活，无需工具装载。两类官方 skill 已装入。
- **脚本型 skill 当前不兼容**：docx/pdf/pptx 等依赖 `scripts/` 里的 bash 命令，
  而 Aris 模型没有通用 bash 工具（工具是注册式），暂不可用。
- **references/ 依赖不可用**：`internal-comms` 等 skill 的激活手册指向
  `examples/` 子文件，而 L3 references 读取工具尚未实现（见「演进方向」），
  激活后模型读不到子文件，故未装入。
- **description 截断阈值**：菜单单条 description 截断从 200 放宽到 500 字符
  （`manager.py _DESC_MAX`）。Anthropic 的 description 可达 400+ 字符且含触发
  关键词（如 doc-coauthoring 列举 PRD/RFC/design doc），截断过短会让模型漏判
  激活时机。
- 引入外部 skill 时注意：SKILL.md 正文仍建议 ≤500 行/5000 token（超长时
  按需拆 references/，L3 工具待实现）；保留原 LICENSE 及版权声明。

## 验证方法

- 单元：`SkillManager` 扫描/菜单/激活/幂等/不存在处理（已跑通，含外部 skill）。
- agent loop 模拟：mock LLM 返回一轮 `activate_skill` 工具调用 + 一轮最终回答，
  验证「激活 → 手册回填 TOOL 消息 → 第二轮基于手册回答」闭环（已跑通）。
- 真实链路：`uv run aris chat` 说「帮我记个备忘：明早9点开产品周会」，
  模型应自主调 `activate_skill("note")` → `note_save`；再问「我之前的备忘是什么」
  应调 `note_read`/`note_list` 并正确回答；数据落盘 `data/notes/`。
- 未激活不污染：新会话中（未激活任何 skill）`registry` 工具表应只含
  `activate_skill` + 内置工具，不含 skill 工具。

## 演进方向（暂不实现，YAGNI）

- L3 references 读取工具：给 `activate_skill` 同引擎的 `skill_read_ref(name, path)`
  工具，按需读 references/ 下文件。
- skill 依赖/元数据拓展（version、author、依赖 pip 包等）。
- 待办清单后续项（知识库、日记、AstrBook）各做成独立 skill，本机制即骨架。