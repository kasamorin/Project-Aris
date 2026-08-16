# 开发进度报告

更新于：2026-08-15（Arch Linux 会话）

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
  - 浏览器链路（Playwright Firefox）已于 2026-08-12 **代码删除**，历史与
    恢复要点留档 `developDoc/WEB-SEARCH.md`
  - 验证：真实模型「查 Python 3.14 新特性」正确触发 web_search → Tavily 返回
    结果 → 模型消化并给出准确总结
- **人格系统（简单版，2026-08-12）**：提示词工程起步，`persona/` 模块落地。
  - 人设文本轻量结构化（简介/性格/语气/边界），从 chat 的一行描述独立成模块
  - 注册 `persona.system_prompt` 服务，session 默认人设改经 `core.call` 获取，
    `--system` 仍可覆盖；服务缺失时用兜底文本（宽容降级）
  - 验证：真实模型默认人设（体现新结构化人设）与 `--system` 覆盖均正确
  - 世界观/人际关系/成长轨迹后续在此演进；实现方式（提示词工程 vs MCP）后续再议
- **统一通讯层（2026-08-12）**：`core/bus` 服务注册表 + 事件总线 + 审计统计。
  - 模块间通讯统一经 `core.call` / `core.provide`，模块间不再直接 import 跨模块调用
  - 核心类实例自注册（`__init__` 里 `provide` 自己的方法），命名 `module.service`
  - 已注册服务：`llm.stream` / `llm.deltas` / `tools.execute` / `loop.run` /
    `loop.set_model` / `persona.system_prompt`；核心链路（chat→loop→llm/tools）
    已全部走总线
  - 明确不走总线的边界：对象构造/装配、同模块内部调用、纯类型引用（Message 等）
  - 详 `developDoc/BUS-ARCHITECTURE.md`
- **联网搜索精简（2026-08-12）**：Playwright 浏览器链路**代码删除**（从未真正
  生效，headless 下 Bing/Google 全触发验证码，Tavily 一直兜底），Tavily 成为
  唯一主链路，工具简化为 `web_search(query)`；移除 playwright 依赖。
  历史与恢复要点留档 `developDoc/WEB-SEARCH.md`
- **web_open 点开读正文（2026-08-12）**：新增 `web_open(id)` 工具。
  - `web_search` 把 id→{title,url} 写入模块级缓存（覆盖式，仅最近一次），
    `web_open` 按 id 抓取网页（httpx + 浏览器 UA + 超时）→ `trafilatura`
    提取正文（过滤导航/页脚/广告）→ markdown 返回（截断省 token）
  - 新增依赖 trafilatura（成熟正文提取库，符合轮子哲学）
  - 失败宽容降级：id 无效 / 抓取失败 / 动态页面正文为空 → 错误文本 JSON
  - 验证：真实模型「查 Rust 2025 新特性 → 点开第 1 条读正文 → 总结」完整链路
    跑通，agent 还主动判断结果不对口并提出换关键词再搜
- **配置体系定案（2026-08-12）**：三个配置源各管一摊。
  - `.env`（ARIS_ 前缀）：启动级/密钥/data_dir/llm_providers_file
  - `config/providers.toml`：LLM 提供方（已从根目录移入）
  - `config/*.toml`（chat/search/logging/audit/notify）：功能可调参数，
    新加载器 `aris/cfgtoml.py`（零新依赖，dataclass 默认值 < toml）
  - 7 组隐式枚举收口为 StrEnum（MessageRole / LoopEventType / TransportKind /
    ApiFormat / FinishReason / WebSearchResultType / AuditKind），~35 处魔法
    字符串替换；实现细节保持模块顶部常量；data 路径统一从 Settings.data_dir 取
  - 详 `developDoc/CONFIG.md`
- **技能系统（Skills）落地（2026-08-12）**：目录化、按需加载的能力扩展机制。
  - 三层渐进式披露：L1 菜单（只读 frontmatter 注入 system prompt）→ L2 激活
    （模型调 `activate_skill(name)`，读 SKILL.md 全文 + 装载 tools.py 工具）→
    L3 详情（references 按需读取，预留）。SKILL.md 正文限定 <500 行，
    长内容拆 references/，激活整篇返回不截断
  - 每个 skill 是一个目录 `skills/<name>/`（SKILL.md + 可选 tools.py +
    references/），新增 `SkillManager`（发现/菜单/激活/幂等），注册
    `skills.menu` 总线服务；`activate_skill` 是 registry 里的常驻工具
  - demo `note`（备忘）skill：`note_save`/`note_read`/`note_list`，
    笔记持久化 `<data_dir>/notes/`
  - 验证：真实模型「记个备忘 → 查看」自主激活 skill 完整链路跑通，未激活
    时 registry 只含 `activate_skill` + 内置工具（不污染）
  - 详 `developDoc/SKILLS.md`
- **联网搜索改 Bing 主链路（2026-08-14）**：`web_search` 由 Tavily 唯一主链路
  改为 **Bing 直连为主 + Tavily 兜底**（多引擎编排）。
  - 背景：Tavily 免费额度有限，且摘要带页面导航噪音（`博客园logo/搜索/订阅数`
    实测混入）；Bing 免费无 key、中文结果好。
  - Bing 实现要点（2026-08-14 实测，缺一不可）：Firefox UA（Chrome UA 需
    sec-ch-ua 配套指纹）+ 先访问首页拿 cookie（MUID 会话）+ 搜索 URL 带
    `form=QBRE` + 查询词 URL 编码；`/ck/a` 重定向链接解码 `u=` base64 参数
    拿真实 URL；BeautifulSoup 解析 `li.b_algo`（新增依赖 beautifulsoup4）。
    不满足时 Bing 偶发返回官网首页等低质量结果（曾实测 `python 3.14 新特性`
    → `Welcome to Python.org`）。
  - 引擎策略：`config/search.toml` 的 `prefer_engine`（默认 `"bing"`，可切
    `"tavily"` / `"auto"` 按查询语言分流），Bing 失败自动降级 Tavily，成功
    引擎如实写入 `engine` 字段。
  - Tavily 摘要清洗：`_clean_snippet` 取最长文本块过滤导航噪音。
  - 验证：真实请求 6/6 稳定返回高质量结果（知乎/python 文档）；`web_open`
    抓取 python 官方文档正文成功、知乎等反爬站宽容降级；engine 降级链路完好。
    LLM 端到端未测（opencode 免费模型 429 限流，与本次改动无关）。
  - 排查过程留档 `developDoc/WEB-SEARCH.md`（curl 直连可行性、中文质量崩坏
    定位到 daed 代理出口、cookie/QBRE 关键参数确认）。
- **开发流程标准化定案（2026-08-14）**：此前一直在 main 直接开发提交，现落地
  AGENTS.md「Git 开发流程」：main 永远稳定可跑（只进合并）、feature 分支开发
  （`feat/`、`fix/`、`docs/`、`refactor/`）+ 本地 `merge --no-ff` 合并后删分支、
  提交信息 commit-msg hook 校验（`.githooks/` + `scripts/install-git-hooks.sh`）、
  里程碑合并 bump minor + 打 `vX.Y.Z` tag。`oldWish` 分支（main 祖先）明确保留勿删。
  v0.2.0 作为首个里程碑 tag。
- **fallback 竞速恢复上层接入（2026-08-15）**：`feat/llm-fallback-race` 分支落地，
  已 `merge --no-ff` 合入 develop 并推送（`docs:` 分支流程亦同此验证 hook 规则）。
  - loop：`iter_events` 新增 `race_model` 参数（传入降级后实际生效的模型时本轮
    走 `llm.race` 竞速，本家 vs 备选）；STALL 占位增量独立产出为 STALL 事件，
    不并入最终回答；DONE 携带 `model_id / degraded / race_possible` 元数据
  - session：`ask()` 新增 `on_stall` / `on_degraded` 回调；维护 `_degraded_model`
    降级恢复状态——降级且可竞速时记住实际生效模型，下一轮竞速回主模型，
    主模型恢复后自动退出降级模式；手动 `/model` 切换也会清降级状态；
    repl（非 TTY）打印占位与降级提示
  - tui：新增 `StallNotice` / `DegradedNotice` 通知类，生成线程经回调入队，
    `_consume` 消费展示（占位独占一行、降级提示单独一行）
  - 验证：新增 `test_llm_upper.py` 26 项（loop 层 3 + session 层 4）+ 旧
    `test_llm_fallback.py` 50 项全部通过，无回归
- **http_request 通用 HTTP 工具（2026-08-15）**：`feat/http-request` 分支落地。
  - 新增 `core.http` 统一 HTTP 服务（`core.call("http.request", ...)`），与 LLM
    请求同理可审计、可复用；不拦截内网（个人本机助手）
  - 新增内置工具 `http_request(url, method, headers, body, max_length, start_index,
    raw)`：参考 kelivo_fetch MCP 设计，补齐 web_open(id) 两个短板（无法直接打开
    对话中出现的 URL、长文无法续读）；支持 POST/PUT/PATCH/DELETE 发请求（body
    自动 JSON 化），为 AstrBook 等外部能力提供接口基础
  - URL 来源规则：只能请求对话中已出现的 URL（用户提供 / web_search 返回 / 之前
    http_request 结果）——服务器侧 host 级软校验（`registry.execute` 支持注入对话
    context，loop 拼好传入）；模型「提过一次即可放行」为固有边界
  - GET + HTML 简化 markdown（trafilatura → bs4 兜底），max_length 有界、
    start_index 续读（缓存最近响应全文）；raw=true 返回原始文本
  - 验证：`test_http_request.py` 26 项（本地 mock server，不依赖外网）+ 旧
    `test_llm_fallback.py` 50 项 / `test_llm_upper.py` 26 项全部通过
- **web 工具一致性重构（2026-08-15）**：web_search / web_open 的 httpx 直连
  统一收口到 `core.http`（行为不变，纯一致性）。
  - `core.http` 新增命名会话（session="xxx"）：同名多次请求复用同一
    httpx.Client（cookie/连接连续），Bing「先首页拿 cookie 再搜索」靠它
    保证 cookie 连续；不传 session 保持每次新建连接
  - `_tavily_search` → `call("http.request", POST, ...)`；`_bing_search` →
    两次 GET（首页 → 搜索）走 `session="bing"`，Firefox UA / form=QBRE
    规则不变；`_do_web_open` → `call("http.request", GET)` +
    `web_common.extract_page`（与 http_request 共用提取逻辑）；`_WEB_UA`
    删除（与 DEFAULT_UA 相同）；httpx 依赖全部移除
  - 旧版实现备份 `web_search.py.bak`（.gitignore 忽略不入库；git 历史亦有）
  - 验证：新增 `test_web_migrate.py` 19 项（mock http.request 服务验证
    路由/会话/UA/Tavily body）+ `test_http_request.py` 命名会话 cookie 连续
    3 项；旧 `test_llm_fallback.py` 50 项 / `test_llm_upper.py` 26 项全通过
- **LLM 提供商与模型管理（阶段一，2026-08-14）**：`feat/provider-model-mgmt` 分支落地
  管理基础（详 `developDoc/LLM-PROVIDER-MGMT.md`）。
  - 提供方 schema 扩展：`default_model`（顶层）+ `LLMModel` 新增
    `context_length` / `capabilities` / `thinking_default`；加载校验重复
    provider/模型 id；default_model 缺失/无效自动兜底第一个可用模型
  - thinking 默认值按模型配置解析：`deepseek-v4-flash-free` 配
    `thinking_default = false`，`aris llm test` 等所有路径默认发
    `{"type":"disabled"}` 消除首字延迟（真机 429 限流未测出延迟改善，属环境问题）
  - `aris llm list`（提供方/模型/密钥状态/元数据，标 `[默认]`）与
    `aris llm check`（配置体检非零退出）命令；doctor 末尾附体检摘要
  - 默认模型配置化：`llm test` / `chat` 的 `--model` 默认值取 `default_model`
  - 顺带修复：uv.lock 与 `__version__` 同步至 0.2.0（此前 bump 遗漏）
- 骨架 v0.1.0：pyproject.toml（uv + src 布局）、.env.example、README.md、.gitignore
- 配置系统定案：pydantic-settings（Arch 上 `uv sync` 跑通）
- 文档：AGENTS.md、开发文档拆分、参考文档同步

## 当前阻塞

- 无

## 待定决策

- 记忆架构（三层记忆模型，构想中、未完善，可能换）
- STT 选型
- Python 静态检查/格式化工具（ruff vs black+isort+flake8）
- 测试框架是否启用 pytest
- 打断 vs 缓存输入策略（见 AGENTS.md 待定节）
- Google 搜索接入方式：Custom Search JSON API 已停新申请（2027-01 停服），
  候选 Gemini API Grounding（每日免费额度）或有头模式过反爬，实现前再定
- ~~persona 实现方式~~（已定：提示词工程起步，2026-08-12，见 AGENTS.md）

## 已知问题（待修）

- **运行 `aris chat` 偶发 Node.js EPIPE 崩溃（2026-08-09，已解决）**：报错
  `node:events:487 throw er; Error: write EPIPE`（Node v24.18.1），发生在
  `uv run aris chat` 启动时。疑因上次会话残留的 Playwright node driver 孤儿
  进程向断裂管道写入所致（当时已加 cleanup 清理，但未真机验证）。
  **2026-08-12 浏览器链路整体删除后，playwright / node 依赖不复存在，Aris
  不再有任何 node 进程来源**（已核实 pyproject/uv.lock 无依赖、src 无残留代码、
  系统无残留进程），实际运行 `aris chat` 验证不再崩溃。历史与清理方案留档
  `developDoc/WEB-SEARCH.md`
- **TUI 状态行覆盖（2026-08-09，已修复）**：模型调用工具前若先输出了文字（如
  "我搜一下"），工具调用提示会把那段文字覆盖掉（`_show_tool` 直接截断
  到 `_state_start`）；且调用完输出紧跟同一行、无空格。已改 `_show_tool`
  区分「状态行活跃=等待首字」与「内容已输出」两种情形，后者另起一行显示
  `[调用工具: 名称]`。脚本验证通过（test_tui_issue2.py，临时脚本已于
  2026-08-15 清理），**待真机验证**。
- **Shift+Enter 换行失效（2026-08-09，已修复）**：当前绑定 CSI-u 序列
  `ESC[13;2u`，但实际输入框插入了「OM」两个字符——说明终端发送的是
  `ESC O M`（SS3 应用键序列）而非 CSI-u。已实测 prompt_toolkit 将 `ESC O M`
  解析为 `Escape`+`O`+`M` 三个键，已加对应绑定（与 CSI-u 并存），
  **待真机验证**。
- **TUI 无法选中/复制文本（2026-08-09，已修复）**：全屏模式下
  `mouse_support=True` 拦截了系统选中（点击被当作光标定位）。已确认
  prompt_toolkit 鼠标事件区分 SHIFT 修饰符，方案定为「Shift+鼠标放行」：
  自定义 `Vt100MouseEvent` 绑定接管鼠标事件，带 SHIFT 修饰时返回
  `NotImplemented`（不消费，终端恢复系统选中），其余委托默认处理器
  （点击定位/滚动）。注意：真正放行依赖终端在 Shift 下禁用 mouse
  reporting（konsole 实测如此）；即使终端仍上报 Shift 事件，应用也会
  忽略、不误触发光标定位。**待真机验证**（konsole Shift+拖拽选中复制）。
  详见 `developDoc/TUI-问题修复.md`（四个问题全部验证通过后删除该文档）

## 下一步

1. LLM 提供商与模型管理（**阶段二，已完成** 2026-08-14）：`aris llm fetch`
   一体式（/models 拉取 + models.dev enrichment + 白名单勾选 UI + 写回）+
   退休机制（`config/retired_models.toml` 宽限期 30 天 + `aris llm retired`
   删除 TUI）已实现并验证，详 `developDoc/LLM-PROVIDER-MGMT.md`。
   后续：真机验证勾选 UI；把真实端点 62 个模型同步进配置并挑选默认模型
2. 行为扩展续：下一个能力类 skill（知识库 / 日记 / 接入 AstrBook 论坛，见项目待办清单）
3. 记忆系统（PostgreSQL + pgvector）→ 人格世界观/关系网演进
4. 语音链路（STT → LLM → TTS）

## 专项优化（暂缓）

- ~~**/models 动态获取模型名**~~（已并入阶段二 `aris llm fetch`，2026-08-14
  定案，见 `developDoc/LLM-PROVIDER-MGMT.md`）
