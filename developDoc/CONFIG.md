# 配置文件体系（CONFIG.md）

> 2026-08-12 定案。本文档是 Aris 配置体系的**唯一权威说明**，
> 新增/修改配置时须同步本文件与 `config/*.toml` 对应条目。

## 三个配置源（各管一摊，勿混）

| 配置源 | 管什么 | 示例 |
|---|---|---|
| `.env`（`ARIS_` 前缀，pydantic-settings） | 启动级参数、密钥、`data_dir`、`llm_providers_file` | `ARIS_LOG_LEVEL`、`DEEPSEEK_API_KEY` |
| `config/providers.toml` | LLM 提供方（base_url / key env 名 / 超时 / transport / 模型） | 每提供方一个 `[[providers.provider]]` 条目 |
| `config/*.toml`（模块级，tomllib 加载） | 功能可调参数：chat / search / logging / audit / notify | `config/chat.toml` 的 `max_rounds` |

**优先级**：代码内 dataclass 默认值 < `config/*.toml`（缺文件/缺键静默用默认）。
**密钥永远只在 `.env`**，任何 toml 不进真实 key（providers.toml 的
`api_key_env` 只是引用 env 变量名）。

## 加载机制（aris/cfgtoml.py）

```python
from aris.cfgtoml import load_config
from dataclasses import dataclass

@dataclass
class SearchConfig:
    timeout_seconds: float = 15.0   # 代码内默认值兜底
    results_count: int = 5

_search_config = load_config(SearchConfig(), "search.toml")
```

- 文件路径：`<项目根>/config/<filename>`（基于 `__file__` 解析，与运行 cwd 无关）。
- 覆盖规则：与 dataclass 字段**同名**的 toml 键覆盖默认值；文件缺失、
  解析失败、键不存在均静默用默认（配置缺失不致命）。
- 类型不校验（toml 解析器保证基本类型；复杂校验由调用方按需做）。

## config/ 目录内容

| 文件 | 模块 | 字段 |
|---|---|---|
| `providers.toml` | core/llm | 提供方定义（模板 `config/providers.example.toml`，**该文件不进 git**） |
| `chat.toml` | chat + behavior/loop | `max_rounds`、`log_rotation_bytes`、`tool_result_preview_len` |
| `search.toml` | behavior/tools/web_search | `timeout_seconds`、`results_count`、`snippet_max_len` |
| `logging.toml` | aris/logging | `file_rotation`、`retention` |
| `audit.toml` | core/audit | `max_records`、`recent_default_limit` |
| `notify.toml` | core/llm/notify | `timeout_seconds` |

## 收口原则（2026-08-12 定案）

- **枚举 → 代码内 `StrEnum`**（逻辑类型，不进配置）：
  `MessageRole` / `LoopEventType` / `TransportKind` / `ApiFormat` /
  `FinishReason` / `WebSearchResultType` / `AuditKind`。
- **实现细节 → 模块顶部带注释常量**（无人会调）：stdin 清缓冲 `65536`、
  audit 毫秒换算、TUI 细节（`_ESC_DOUBLE_GAP` / `_SPINNER_INTERVAL` /
  `_INPUT_MAX_HEIGHT`）、`thinking` 关闭体、模糊匹配参数等。
- **真正可调参数 → `config/*.toml`**（新需求可调时，先在模块加 dataclass
  字段再进 toml，不新增 env 入口）。

## 路径约定

- `data_dir` 单一来源：`config.py` 的 `Settings.data_dir`（默认 `data/`），
  各模块通过 `get_settings()` 获取，**不在模块里重复定义默认路径**。
- `XDG_RUNTIME_DIR`：notify 自动探测（`/run/user/<uid>`），不硬编码。

## 常见操作

- 新增可调参数：模块加 `@dataclass` 字段（带默认值）→ `load_config(...)`
  模块级单例 → 对应 `config/*.toml` 补键（可省，默认值兜底）。
- 加新 toml 文件：`config/` 下新建 → 本文件登记一行 → AGENTS.md 若涉及改表。
