# 联网搜索方案留档（WEB-SEARCH.md）

> 本文件记录项目联网搜索方案的完整演进历史，包括**已删除**的 Playwright
> 浏览器链路（勿再实现）与当前唯一主链路 Tavily。AGENTS.md 已定案节为
> 权威结论，本文档补充实现细节与恢复要点。

## 当前方案（2026-08-12 起，唯一主链路）

**Tavily API 搜索**：`src/aris/behavior/tools/web_search.py`

- 专为 LLM 设计、无反爬，`TAVILY_API_KEY` 走 `.env`（运行时读取环境变量）。
- 工具签名：`web_search(query: str)`，不再暴露 `engine` 参数（单引擎无需选择）。
- 返回格式（外层 JSON 标识 + 内部 markdown 省 token）：

  ```json
  {"type": "web_search_results", "query": "...", "engine": "tavily",
   "results": "1. [标题](url)\n   摘要\n2. ..."}
  ```

- 每条结果自带自增 id（第 1 条为 1）。`web_search` 同时把 id→{title, url}
  写入模块级缓存 `_recent_results`（覆盖式，仅保留最近一次搜索），
  供 `web_open` 按 id 点开读正文。
- 失败策略：Tavily 失败（无 key / 网络 / 无结果）返回
  `{"type": "web_search_error", ...}` 错误文本 JSON 给模型消化，宽容降级不抛 UI。
- 摘要截断长度等可调参数在 `config/search.toml`（`timeout_seconds`、
  `results_count`、`snippet_max_len`）。

**网页正文读取**（`web_open(id: int)`，同文件）：

- 按 id 从 `_recent_results` 取 url → `httpx` GET（浏览器 UA + 超时 + 跟随重定向）
  → `trafilatura` 提取正文纯文本（过滤导航/页脚/广告）→ markdown 返回。
- 返回格式：

  ```json
  {"type": "web_open_result", "id": 2, "content": "# 标题\n\n原文链接：...\n\n正文…"}
  ```

- 失败降级：id 不在最近结果 / 抓取失败 / 正文提取为空（动态渲染页面）→
  `{"type": "web_open_error", "id": ..., "error": "..."}`。
- 正文长度截断（默认 4000 字符）与抓取超时（默认 20s）在 `config/search.toml`
  （`webopen_timeout_seconds`、`webopen_max_chars`）。
- 注意：`web_open` 只能点开**最近一次** `web_search` 的结果，搜索新关键词后
  旧 id 失效（覆盖式缓存）。agent 可自主多轮换搜索词（试错）。
- 局限：不适用于 JS 动态渲染页面（正文提取为空）；国内源未做深抓。

### 后续方向（未定，勿现在实现）

- 国内源深抓（正文提取 + 反爬处理）。
- Google Custom Search JSON API 已停新申请（2027-01 停服），不可用。
- 可考虑 Gemini API Grounding（每日免费额度）接 Google 搜索。

## 演进历史

### 阶段一：Playwright 驱动系统 Firefox（2026-08-09 尝试，失败）

原定用 Playwright 驱动**系统品牌版 Firefox** 做搜索降级链路。
实测**不可行**：Playwright 官方不支持品牌版 Firefox（依赖 Mozilla 私有补丁），
无法连接。

### 阶段二：Playwright 自带 Firefox 二进制（2026-08-09 尝试，反爬失败）

改用 Playwright 自带的 Firefox 二进制（`playwright install firefox`）。
实测 headless 模式下访问 **Bing / Google 均触发验证码反爬拦截**，拿不到结果。

结论：浏览器链路在 headless 场景下基本不可用，实际搜索以 Tavily 为主。
曾保留浏览器代码作为「将来尝试有头模式/换引擎」的扩展点。

### 阶段三：删除浏览器链路，只留 Tavily（2026-08-12 定案）

浏览器链路从未真正作为搜索入口生效过（Tavily 一直兜底），保留它只会：
- 增加依赖面：`playwright` 包 + `playwright install firefox` 二进制下载。
- 增加维护面：`BrowserManager`（惰性启动/孤儿进程清理/生命周期）+ 两个
  引擎的选择器解析（`.b_algo` / `div.g`），与「可维护性最高优先级」冲突。
- 影响后续统一通讯层迁移（`browser.close` / `browser.cleanup` 服务）。

**定案**：删除全部浏览器链路代码，Tavily 成为唯一主链路。

### 已删除代码（勿再实现，恢复要点）

| 文件 | 职责 | 恢复要点 |
|---|---|---|
| `behavior/browser.py` | `BrowserManager` 管理 Playwright Firefox 生命周期 | 惰性启动（首次用才 start）、常驻 profile（`data/firefox-profile/`）、`cleanup_stale_browser_processes` 按 driver 路径 + profile 目录特征精确匹配清孤儿进程（pgrep -a -f）与锁文件 |
| `behavior/web.py` | 驱动浏览器访问 Bing/Google 并解析结果 | 选择器：Bing `li.b_algo` + `.b_caption p`，Google `div.g` + `h3`；`_SEARCH_TIMEOUT_MS = 15000`；无结果抛异常由上层换引擎 |
| `tools/web_search.py` 浏览器分支 | Google 失败降 Bing、双引擎失败降 Tavily | `_GOOGLE_FAILS_TO_PREFER_BING = 3` 连续失败把 Bing 提为优先；模块级 `_prefer_bing` 跨调用保持 |

若未来必须上浏览器方案（如有头模式验证可行），需重新引入 `playwright`
依赖 + 二进制，并恢复上述文件；届时建议先用有头模式验证反爬是否可过，
再决定是否值得。

## 设计约定（两种方案共有的，现在仍生效）

- 返回**外层 JSON 标识**是联网搜索结果，内部用 markdown 省 token。
- 每条结果**自增 id**，供后续 `web_open` 按 id 点开读正文。
- agent 可自主**多轮换搜索词**（试错）。
- 首期只出搜索列表，点开读正文、国内源深抓后续再加。
