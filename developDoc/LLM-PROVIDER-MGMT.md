# LLM 提供商与模型管理（LLM-PROVIDER-MGMT.md）

> 2026-08-14 定案。对应待办清单第 1 项「完善提供商和可用模型管理」。
> 本文档是 provider/model 管理功能的**唯一权威说明**，分两阶段落地：
> 阶段一（管理基础）与阶段二（/models 同步 + 退休机制）。

## 背景与痛点

- 模型列表纯手写 `config/providers.toml`：新增提供方要手工抄模型名，易错、易过时。
  实测 OpenCode Zen `/models` 返回 62 个模型，而现有配置里的
  `ling-3.0-tiny-free`、`longcat-2.0-free`、`north-mini-code-free` 已不在端点，
  端点新增了 `hy3-free`、`nemotron-3.5-lightning-free` 等。
- 默认模型 `deepseek-v4-flash-free` 硬编码在 `cli.py` 两处。
- 无管理命令：不能一次看全所有提供方、不能体检 key 是否就位、配置错误（重复 id、
  缺 key）只在运行时才暴露。
- 模型零元数据：无上下文长度、能力（工具/思考/视觉），无法为自动选型打底。
- `aris llm test` 路径不传 `thinking`，走提供方默认（思考开启）导致首字延迟。

## 现状梳理

- 数据模型在 `src/aris/core/llm/config.py`：`LLMModel`（id/name/request_name/formats）、
  `LLMProvider`（id/name/base_url/api_key_env/timeout/transport/models）、
  `ProviderConfig`（order 决定 fallback 顺序，`candidates_for`/`all_model_ids`）。
- 配置：`config/providers.toml`（不进 git）+ `providers.example.toml` 模板。
- fallback：`LLMEngine` 按统一模型 id 找候选提供方，报错切下家 + 总体超时预算。
- 已注册服务：`llm.stream` / `llm.deltas`（engine 自注册）。

---

## 阶段一：管理基础

### 1.1 schema 扩展（config.py + providers.toml）

顶层新增：

```toml
default_model = "deepseek-v4-flash-free"   # 默认统一模型 id（CLI 无 --model 时使用）
```

`LLMModel` 新增可选字段（向后兼容，缺省即用默认）：

```python
@dataclass
class LLMModel:
    id: str
    name: str
    request_name: str
    formats: list[str] = field(default_factory=lambda: [ApiFormat.CHAT])
    context_length: int | None = None          # 上下文窗口（tokens）
    capabilities: list[str] = field(default_factory=list)  # 能力关键词
    thinking_default: bool | None = None       # 默认思考开关（None=跟随提供方）
```

- `capabilities` 自由关键词，约定：`tools` / `reasoning` / `vision`。
- `thinking_default=false`：未显式指定 thinking 时默认关闭思考模式。

`ProviderConfig` 新增：

```python
default_model: str | None = None
```

加载校验（`load_providers`）：
- provider id 重复 → `ProviderConfigError`。
- 同 provider 内模型 id 重复 → `ProviderConfigError`。
- `default_model` 未配置 → 取 order 第一个提供方的第一个模型并记警告（自动兜底）。
- `default_model` 配置了但不存在 → 记警告 + 兜底同前。

### 1.2 thinking 默认值按模型配置解析（engine.py）

- `ChatRequest.thinking` 三态：`True`（强制开启）/ `False`（强制关闭）/ `None`（未指定）。
- `None` 时由 engine 解析为模型 `thinking_default`：`False` → 请求体加
  `thinking: {"type": "disabled"}`；`True`/`None` → 不传（跟随提供方默认）。
- 覆盖规则：显式 `--thinking`/`--no-thinking` 永远优先于模型配置。
- 效果：`deepseek-v4-flash-free` 配 `thinking_default = false` 后，所有路径
  （含 `aris llm test`）默认发 `{"type": "disabled"}`，消除首字延迟。

### 1.3 管理命令（cli.py）

```
aris llm list    # 列出全部提供方 + 模型 + 密钥状态 + 元数据，默认模型标 [默认]
aris llm check   # 配置体检，有错误时非零退出
```

`llm list` 输出结构：

```
提供方: opencode (OpenCode)
  地址: https://opencode.ai/zen/v1 | 传输: sdk | 密钥: OPENCODE_API_KEY [就位]
  模型:
    - deepseek-v4-flash-free [默认]  context: 200K  capabilities: tools, reasoning
    - big-pickle                     context: 200K  capabilities: tools
```

`llm check` 体检项：
- 重复 provider id / 同 provider 重复模型 id / order 引用不存在的 provider id
- `default_model` 缺失或不存在于任何提供方
- 每提供方 `api_key_env` 对应的环境变量是否已在 `.env` 配置
- 提供方模型列表为空

`doctor` 末尾附一段 `llm check` 摘要（不改变 doctor 退出码逻辑）。

### 1.4 默认模型配置化（cli.py + session.py）

- `llm test --model` / `chat --model` 的默认值从 `load_providers().default_model` 解析。
- `chat /model` 无参展示时标出 `[默认]`，切换逻辑不变。

---

## 阶段二：/models 同步 + 退休机制

### 2.1 命令形态（一体式 fetch）

```
aris llm fetch [provider_id] [--refresh] [--dry-run] [--write]
             [--add id,...] [--keep id,...] [--delete id,...]
aris llm retired              # 退休模型管理 TUI（手动删除）
```

- 默认 provider = `default_model` 所在提供方（或 order 第一个）。
- `--refresh`：强制重新下载 models.dev 缓存。
- `--dry-run`（默认）：只打印完整 diff（含退休巡检结果），不落盘。
- `--write`：应用变更（勾选结果 / 或非 TTY 全量对齐）。
- `--add/--keep/--delete`：非 TTY 下细粒度覆盖（白名单语义）。

### 2.2 核心流程

```
GET {base_url}/models（httpx，复用 key；无 key 匿名尝试，401 明确提示）
        ↓ 得到云端模型集
三方对比（vs providers.toml 活跃模型）：
  云有本地无  → 添加候选（元数据 enrichment 后进勾选 UI）
  两边都有    → 保留
  本地有云无  → 移入退休文件 + 从可选列表移除 + 提示
退休文件巡检（config/retired_models.toml）：
  回归端点    → 自动恢复进 providers.toml，清退休记录
  未回归      → 保留，等待下次
  超 30 天    → 自动永久删除（记日志 + 提示）
```

### 2.3 添加候选勾选 UI（按系列分组）

- 端点新模型按前缀系列分组分页（`claude-*` / `gpt-*` / `*-free`...），
  空格勾选/取消，`p`/`n` 翻页，回车确认。
- 每条展示 models.dev 元数据（name / context / tools / reasoning / vision），
  同系列一眼挑中需要的那个（白名单语义，替代 --filter 粗筛）。
- 已退休模型不在此列表出现。

### 2.4 models.dev enrichment

- 数据源：`https://models.dev/api.json`（约 3.6MB 单文件全量，
  `{provider_id: {models: {model_id: {...}}}}`，215 家提供方）。
- 缓存：`<data_dir>/models-dev.json`，TTL 7 天（`--refresh` 强制更新）。
- 字段映射（`limit`/`cost`/`modalities`/`tool_call`/`reasoning`）：

| models.dev 字段 | 写入 LLMModel |
|---|---|
| `name` | `name` |
| `limit.context` | `context_length` |
| `tool_call` | `capabilities` + `tools` |
| `reasoning` | `capabilities` + `reasoning` |
| `modalities` 含图像 | `capabilities` + `vision` |

- 未收录（如 zen 免费模型）→ 标「models.dev 未收录」，字段留空手动补。

### 2.5 退休机制（config/retired_models.toml）

```toml
[[retired]]
provider = "opencode"
model = "ling-3.0-tiny-free"
first_missing = "2026-08-14"   # 首次失联日期，宽限期起算
```

- 文件**机器维护**，不手工编辑；放 config/ 与 providers.toml 同目录。
- 每次 fetch 巡检：回归 → 恢复并清记录；`first_missing` 距今 >30 天 → 永久删除。
- `aris llm retired`：TUI 列出退休模型，空格选中 + 回车删除。
- 幂等：重复 fetch 不产生重复条目。

### 2.6 非 TTY 语义

- `--dry-run`：打印完整 diff（新增/保留/退休/回归/过期）。
- `--write`：全量对齐（新增全加、缺失全退休）；`--add/--keep/--delete` 覆盖。
- 写回前备份 `providers.toml` → `providers.toml.bak`。

---

## 代码落点

| 文件 | 职责 |
|---|---|
| `src/aris/core/llm/config.py` | schema 扩展 + 加载校验（阶段一） |
| `src/aris/core/llm/engine.py` | thinking 默认值按模型配置解析（阶段一） |
| `src/aris/core/llm/fetch.py` | 拉取/对比/enrichment/写回/退休巡检（阶段二，新） |
| `src/aris/cli.py` | `llm list` / `llm check` / `llm fetch` / `llm retired` + doctor 摘要 |
| `src/aris/chat/session.py` | `/model` 标 `[默认]` |
| `config/providers.toml` / `providers.example.toml` | `default_model` + 模型元数据 |
| `config/retired_models.toml` | 退休记录（阶段二，机器维护，新） |

依赖：httpx / prompt_toolkit / tomllib / tomli-w（tomli-w 新增，写回用）。

## 验证清单

- 阶段一：`aris llm list` / `aris llm check`（构造重复 id、缺 key 场景）/ 
  `aris llm test`（观察 dsv4ff 首字延迟）/ `aris chat` 切换模型。
- 阶段二：`aris llm fetch --dry-run`（对比真实端点）/ 勾选写回 / 退休模拟
  （手工造一个本地有云无的模型，验证移入退休、恢复、30 天过期）/ 幂等重复 fetch。
