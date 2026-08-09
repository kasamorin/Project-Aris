# 开发进度报告

更新于：2026-08-09（Arch Linux 会话）

## 已完成

- **LLM 连接层（2026-08-09）**：`core/llm` 模块落地并跑通流式对话。
  - LLM 选型定案：多提供方抽象 + fallback，本次实现 OpenAI Chat Completions 格式
  - 统一请求模板（Message / ChatRequest）+ formatters 按 format 翻译请求体
  - 双传输：openai SDK（默认） + httpx 手写（SSE），从一开始就流式（TTS 增量需要）
  - fallback：报错即切下家；总体超时预算（默认 30s，含切换耗时）耗尽则进错误处理
  - 错误处理：不暴露原始报错，返回预设提示语 + 错误广播（桌面弹窗 + 推送注册接口）
  - 配置：`providers.toml`（toml 定义 provider/模型结构，不进 git）+ `.env` 放密钥
  - 验证：`aris llm test` 子命令流式实测；本地 mock 验证 sdk/httpx/fallback/超时四链路
  - **bug 修复**：pydantic-settings 读 .env 不注入 os.environ，`transport._api_key`
    改为经 `config._load_env_into_environ()` 同步后再读，CLI 跑通
- **文字对话跑通（2026-08-09）**：`aris chat` 子命令。
  - 两种形态：带消息参数走单次问答，不带则进入交互循环（`/help` 查看指令，`/quit`、`/exit` 退出）
  - 会话历史存内存（当前进程内多轮上下文），退出即清空
  - 每轮问答追加落盘 `<data_dir>/logs/YYYY-MM-DD/chat.log`（人类可读格式，供回溯/记忆接入）
  - 默认内置简单 Aris 人设提示词（`chat.ARIS_SYSTEM_PROMPT`），可用 `--system` 覆盖
  - 默认模型 deepseek-v4-flash-free，`--model` 切换任意已配置模型
  - 交互输入用 prompt_toolkit（修复中文删除/重叠问题）；控制台日志默认安静，
    `--verbose` 显示 INFO（对话日志全量落文件）
  - **模块重构（2026-08-09）**：独立为 `chat/` 包（`session.py` 会话 + `tui.py` 全屏界面 +
    `commands.py` 指令），`/help` 查看可用指令；TUI 支持 ESC 两次中断回复、Ctrl-C 退出
  - **交互补全（2026-08-09）**：多行输入（Enter 发送，Shift+Enter 换行——需终端支持
    CSI-u 扩展，kitty/wezterm/foot 等；不支持时 Alt+Enter 换行兜底）；上下方向键回看
    输入历史；新增指令 `/clear`（清屏）、`/new`（清空历史重开会话）、`/model [id]`
    （查看/切换模型）；指令统一由 `session.run_command` 分发（返回文本+quit/clear 标记），
    TUI 与非 TTY 回退共用；`core/llm/config.py` 新增 `ProviderConfig.all_model_ids()`
- **OpenCode Zen 免费模型接入（2026-08-09）**：8 个免费模型（`*-free`、`big-pickle`）
  全部走 `/chat/completions`（已实测 + `/models` 接口核实），加入 `providers.toml`
- **日志结构升级（2026-08-09）**：按天文件夹 + 大小轮转——`data/logs/YYYY-MM-DD/`
  内含 `aris.log`（系统日志，loguru 10MB 轮转）与 `chat.log`（对话日志，手动 10MB 切分），
  跨天自动建新目录，仅保留 30 天
- **Embedding 定案（2026-08-09）**：热记忆本地 Bekko a25m（OpenVINO CPU），冷记忆
   云端 Cloudflare BGE-M3；两库维度不同（384/1024）各建独立 pgvector 表。详见
   `developDoc/EMBEDDING.md`
- **函数调用跑通（2026-08-09）**：原生 tool_calls + agent loop。
  - `Message` 扩展：`tool_calls`/`tool_call_id`/`reasoning_content`（DeepSeek 带 tools
    必须回传思考链否则 400），content 放宽 `str|None`；`ChatRequest` 加
    `tools`/`tool_choice`/`thinking`；新增 `ToolCall`（arguments 归一化为 dict）与
    `ToolDefinition`（name/description/parameters JSON Schema）
  - 流式 tool_calls 按 index 分片拼装（SDK/httpx 两条路径），流结束发「完成事件」
    （finish_reason + 完整 tool_calls）；`engine.stream_deltas()` 公开，`stream()`
    保持纯文本
  - `behavior/` 模块：`registry.py`（工具注册表，执行失败宽容降级回填给模型）、
    `loop.py`（agent loop：请求→流式→完成事件→执行→回填→再请求，最多 8 轮）、
    `tools/get_current_time.py`（首个内置工具）；中间轮不污染持久历史（chat.session 只收最终回答）
  - 思考模式实测：Zen 模型默认思考（首字延迟 7s+），`thinking:{"type":"disabled"}`
    有效关闭；chat 默认关闭思考，`--thinking` 开启
  - 接入 chat：`session.ask` 走 agent loop，工具调用经 `on_tool` 回调显示在 TUI
    （`[调用工具 get_current_time → ...]`）；`--no-tools` 可禁用
  - 验证：mock 分片 tool_calls 实测完整链路；**真实模型实测**「现在几点了？」
    正确触发 get_current_time 工具并返回准确时间（含拟人口吻）。工具返回结构化
     dict（year/month/day/hour/minute/second/weekday 及中文/ISO 编号/时区偏移），
     模型按需提取表达
- **联网搜索跑通（2026-08-09）**：`web_search` 工具注册进 registry。
  - Tavily API 为主链路（`.env` 里 `TAVILY_API_KEY`），返回外层 JSON
    （`web_search_results` 标识）+ 内部 markdown 列表（每条带自增 id 供后续
    `web_open` 点开），摘要截断省 token
  - 浏览器链路（`behavior/browser.py` 管理 Playwright Firefox 生命周期、
    `behavior/web.py` Bing/Google 解析）代码保留：官方不支持品牌版 Firefox，
    headless 下 Bing/Google 均触发验证码，作为将来有头模式/换引擎的扩展点
  - chat 会话持有 BrowserManager（惰性启动、会话结束 close 释放）
  - 验证：真实模型「查 Python 3.14 新特性」正确触发 web_search → Tavily 返回
    结果 → 模型消化并给出准确总结
- 骨架 v0.1.0：pyproject.toml（uv + src 布局）、.env.example、README.md、.gitignore
- 配置系统定案：pydantic-settings（Arch 上 `uv sync` 跑通）
- 文档：AGENTS.md、开发文档拆分、参考文档同步

## 当前阻塞

- 无

## 待定决策

- 记忆架构（三层记忆模型，构想中、未完善，可能换）
- STT 选型
- persona 实现方式（提示词工程 vs MCP，模块已搁置）
- Python 静态检查/格式化工具（ruff vs black+isort+flake8）
- 测试框架是否启用 pytest
- 打断 vs 缓存输入策略（见 AGENTS.md 待定节）
- Google 搜索接入方式：Custom Search JSON API 已停新申请（2027-01 停服），
  候选 Gemini API Grounding（每日免费额度）或有头模式过反爬，实现前再定

## 下一步

1. ~~跑通文字对话~~（已完成，`aris chat`）→ 记忆系统（PostgreSQL + pgvector）
2. 行为扩展续：联网搜索（**已完成**：Tavily 主链路 + 浏览器扩展点，见 AGENTS.md
   定案节）、web_open（按 id 点开读正文）、MCP 服务器、Skills
3. 语音链路（STT → LLM → TTS）

## 专项优化（暂缓）

- **/models 动态获取模型名**：`GET {base_url}/models` 返回 `data[].id`，
  opencode 用静态目录（Models.dev）不从该接口动态拉；Aris 后续可加
  `fetch_models()` 免手填 providers.toml 模型名（`aris llm test --list-models`）
