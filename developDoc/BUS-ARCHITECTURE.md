# 统一通讯层（core.bus）架构文档

> 2026-08-12 定案并落地。本文档是统一通讯层的**唯一权威说明**，
> 后续改动 bus 相关代码或新增服务时，须同步更新本文件。

## 背景与动机

项目早期模块间直接 `import` 互相拉通（`chat.session → behavior → core.llm`），
存在三个问题：

1. **耦合**：后期加模块（auto 定时任务、memory、voice、persona）时，
   模块间会形成蜘蛛网式依赖。
2. **不可观测**：模块间互相调用了什么、耗时多少、成功与否，完全不可查，
   后期做 WebUI 监控无从下手。
3. **不可替换**：想 mock / 换实现（如测试时替换 LLM）需要改调用方。

**最终决策**：在 `core/` 建立统一通讯枢纽 `bus`，所有模块间通讯
（同步服务调用 + 事件广播）统一经过它。

## 关键决策记录（防止后人走回头路）

### 1. 为什么不用 C 做通讯层（已否决，勿再提）

曾设想用 C 语言加子模块做统一通讯层，所有通讯经 ctypes 中转。
**否决理由**（商讨结论）：

- ctypes 传复杂对象（dict / Message / ToolCall）需要序列化，每次通讯
  多两趟序列化开销，且要维护一层 C 胶水类型。
- 通讯是逻辑编排问题，不是性能问题；Python 层函数调用开销极小。
- 与 AGENTS.md 既定哲学冲突：KISS + 轮子哲学 +「重活用成熟库」。
  项目已明确否定过「用 C 做配置解析」，通讯中转是同类问题。
- C 扩展跨平台（Arch x86_64 / Termux aarch64）要维护两套编译，
  与「可维护性最高优先级」目标冲突。
- 后续商讨进一步澄清：即便 C 只「流经不接手」（只统计不转发），
  统计只需元数据、不涉及消息内容，Python 层完全足够。

**C 子模块定位不变**：只做性能敏感点（Embedding 推理、GraphRAG 算子、
音频 DSP 等），维持 `csrc` 现有「可选编译、失败降级」模式。

### 2. 为什么用「实例自注册」而非集中注册

两种方案权衡：
- 集中注册（`core/__init__.py` 统一 `provide`）：一眼可查全部服务，
  但实例需层层传递到注册处，组装复杂。
- **实例自注册（采用）**：核心类（LLMEngine / ToolRegistry / AgentLoop）
  在 `__init__` 里自行 `provide` 自己的方法。创建即注册，最不易遗漏；
  重名覆盖会打 warning 日志，可发现重复实例化问题。

### 3. 命名规范

- **服务**：`module.service` 两级，如 `llm.stream`、`llm.deltas`、
  `tools.execute`、`loop.run`。
- **事件**：`domain.event` 两级，如 `memory.saved`、`voice.ready`（规划）。
- **前缀**：`core.` 是模块名不是项目名——项目名 aris 随时可能改，
  函数名绝不含 `aris`，减小改名成本。

## 架构总览

```
模块 A ── core.call("llm.stream", req) ──┐
                                         ├──> core.bus ──> 已注册服务
模块 B ── core.emit("memory.saved", p) ──┘         │
                                                   └──> core.audit（记录流水）
```

- 服务调用（call/provide）：同步、一对一、有返回值
- 事件（emit/subscribe）：一对多、解耦、同步分发（当前无跨进程需求）
- 审计（audit）：每次通讯记录时间戳/目标/耗时/成败，环形缓冲可查

## 代码位置与 API

### `src/aris/core/bus.py` —— 服务注册表 + 事件总线

```python
from aris.core import call, emit, provide, subscribe, query_recent, query_summary

# 注册服务（实例自注册，重名覆盖 + warning）
provide("llm.stream", engine.stream)

# 调用服务（同步；服务不存在返回 None + 模糊匹配建议日志）
result = call("llm.stream", request)

# 事件订阅与发布
subscribe("memory.saved", handler)   # handler(payload)
emit("memory.saved", payload)

# 审计查询
records = query_recent(limit=50)     # 最近流水（新→旧）
summary = query_summary()            # 聚合统计
```

**健壮性保证**（对应「后期加模块也稳」的需求）：
- 服务不存在：返回 `None`，打 ERROR 日志 + `difflib` 模糊建议
  （"是不是想调用: xxx"）。
- 服务执行抛异常：透传异常给调用方，但先记审计 `ok=False`。
- 事件无订阅者：静默丢弃（事件是松耦合通知，不强求接收方）。
- 事件单个订阅者异常：不影响其他订阅者（逐 handler try/except）。
- 审计记录失败：静默降级，绝不拖累业务调用。
- 线程安全：注册表/订阅表都用 `threading.Lock`，为将来 auto 模块的
  后台线程调用预留。

### `src/aris/core/audit.py` —— 审计统计层

- 内存环形缓冲（`deque(maxlen=2000)`），只留最近 2000 条，防内存膨胀。
- `AuditRecord`：kind（call/event）、target、ts、duration、ok、detail。
- 全局单例 `default_audit`，bus 直接调用。
- 聚合统计：按目标合并（count / total_ms / avg_ms / errors）。

## 服务注册表（当前全部服务）

| 服务名 | 注册来源 | 用途 | 调用方 |
|---|---|---|---|
| `llm.stream` | `LLMEngine.__init__` | 纯文本流式（简单场景） | `cli.py llm test` |
| `llm.deltas` | `LLMEngine.__init__` | 完整增量流式（含完成事件/tool_calls） | `behavior/loop.py` |
| `tools.execute` | `ToolRegistry.__init__` | 执行工具，返回文本结果 | `behavior/loop.py` |
| `loop.run` | `AgentLoop.__init__` | 跑完整「LLM↔工具」循环，产出事件流 | `chat/session.py` |
| `loop.set_model` | `AgentLoop.__init__` | 切换模型：更新 loop 内部 model id | `chat/session.py` |
| `persona.system_prompt` | `persona/__init__.py` | 返回 Aris 系统提示词 | `chat/session.py`（默认人设，`--system` 可覆盖） |

> 注：曾规划 `browser.close` / `browser.cleanup` 服务，因浏览器链路
> （Playwright）已整体删除（2026-08-12，见 `developDoc/WEB-SEARCH.md`），
> 不再需要。

## 迁移状态

### 已迁移（第一批：核心链路，贯穿 chat/behavior/core.llm）

- `behavior/loop.py`：内部调 `llm.deltas` / `tools.execute` 走总线；
  自身注册 `loop.run`。
- `chat/session.py`：调 `loop.run` 走总线。
- `cli.py` `llm test`：调 `llm.stream` 走总线。

### 已迁移（第二批：persona，2026-08-12）

- `persona/__init__.py`：模块级 `provide("persona.system_prompt")`。
- `chat/session.py`：默认系统提示词从本地硬编码改为
  `call("persona.system_prompt")`（服务缺失时用兜底文本），`--system` 可覆盖。

> 注：persona 无核心类实例，采用模块级注册（import 即注册）；服务注册表是
> 全局的，模块加载顺序无关紧要——session 在构造时经 call 获取即可。

### 明确不走总线（设计边界）

- **对象构造 / 装配**（依赖注入）：`session` 构造 `BrowserManager`、
  `ToolRegistry`、`AgentLoop`，`register_builtin_tools` 注册工具——
  这些是装配动作，直接 import 引用，不视为「模块间通讯」。
- **同模块内部调用**：`behavior` 内部各文件间（browser/web/tools）互调，
  不走总线（同一模块无需解耦）。
- **CLI 组装**：`cli.py` 创建 engine/session，属于组装根，保持直接引用。
- **纯数据/类型引用**：`Message`/`ChatRequest`/`ToolDefinition` 等
  数据结构跨模块共享，import 类型即可，不经总线。

### 未迁移（遗留，后续视需要处理）

- ~~`session.py` 中 `self.browser.close()`、`cleanup_stale_browser_processes()`~~
  → **已随浏览器链路删除**（2026-08-12），无需处理。
- `loop.set_model` 已注册为 `loop.set_model` 服务（见服务表），
  `session.set_model` 经 `call("loop.set_model", model_id)` 调用，已完成迁移。

## 后续待办

1. **事件总线首个真实使用者**：memory 模块入库成功时 emit
   `memory.saved`；voice 就绪时 emit `voice.ready`，验证事件链路。
2. **WebUI**：审计查询接口（query_recent / query_summary）为将来
   WebUI 监控预留，暂未做前端。

> 枚举/魔法字符串收口与配置集中化**已完成**（2026-08-12）：
> 7 组隐式枚举收为 StrEnum，可调参数进 `config/*.toml`，见 `developDoc/CONFIG.md`。

## 验证方法

- 单元级：`test_bus.py`（注册/调用/覆盖/异常/事件/审计/模糊建议）已跑通后删除。
- 链路级：mock LLM 的 agent loop 测试（`test_loop_bus.py`）验证
  delta→tool→delta→done 事件序列 + 审计计数，跑通后已删除。
- 端到端：`uv run aris llm test` 真实流式调用验证（走总线）。
- 回归：`uv run aris chat` 真实对话含工具调用。
