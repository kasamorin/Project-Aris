# 联网搜索方案留档（WEB-SEARCH.md）

> 本文件记录项目联网搜索方案的完整演进历史，包括**已删除**的 Playwright
> 浏览器链路（勿再实现）与当前主链路 Bing 直连 + Tavily 兜底。AGENTS.md
> 已定案节为权威结论，本文档补充实现细节与恢复要点。

## 当前方案（2026-08-14 起：Bing 直连为主 + Tavily 兜底）

**`src/aris/behavior/tools/web_search.py`**，多引擎编排：

- **Bing 直连（默认主链路）**：HTTP 直连 `www.bing.com` 搜索页，无 API key、零成本。
  - 关键实现细节（2026-08-14 实测，**缺一不可**）：
    - **Firefox UA**（Chrome UA 需 sec-ch-ua 系列头配套指纹，否则被识别为爬虫）
    - **先访问首页拿 cookie**（`MUID` 等会话），再搜索。不带 cookie 时 Bing 偶发
      返回官网首页等低质量结果（实测 `python 3.14 新特性` → `Welcome to Python.org`）
    - 搜索 URL 带 **`form=QBRE`** 参数（真实浏览器搜索请求均带）
    - 查询词必须 `urllib.parse.quote` URL 编码（中文不编码直接 400）
  - 链接解码：结果 href 是 `/ck/a` 重定向包装，取 `u=` 参数（`a1` 前缀 + base64
    真实 URL）解码拿真实链接；解码失败保留原链接（web_open 跟随重定向兜底）。
  - 解析：BeautifulSoup 定位 `li.b_algo`，标题 `h2 a`、摘要 `p`。
  - 稳定性实测：带 cookie 会话后 6/6 稳定返回高质量结果（知乎/腾讯云 + python 文档）。
- **Tavily 兜底**：`TAVILY_API_KEY` 走 `.env`，Bing 失败（限流/断连/无结果）时自动降级。
- **引擎顺序**：`config/search.toml` 的 `prefer_engine`（默认 `"bing"`；可切
  `"tavily"`，或 `"auto"` 按查询语言分流——含中文走 Tavily）。Bing 失败时
  自动降级 Tavily，成功引擎如实写入返回 JSON 的 `engine` 字段。
- **摘要清洗**：`_clean_snippet` 对摘要做 HTML 实体解码 + 折叠空白 + 取最长文本块，
  过滤 Tavily content 里的页面导航噪音（实测博客园 `logo/搜索/写随笔` 等）。

**网页正文读取**（`web_open(id: int)`，同文件，未变）：

- 按 id 从 `_recent_results` 取 url → `httpx` GET（浏览器 UA + 超时 + 跟随重定向）
  → `trafilatura` 提取正文纯文本（过滤导航/页脚/广告）→ markdown 返回。
- 返回格式：

  ```json
  {"type": "web_open_result", "id": 2, "content": "# 标题\n\n原文链接：...\n\n正文…"}
  ```

- 失败降级：id 不在最近结果 / 抓取失败 / 正文提取为空（动态渲染页面）→
  `{"type": "web_open_error", "id": ..., "error": "..."}`（如知乎等反爬站）。
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

### 阶段四：Bing 直连主链路（2026-08-14 定案）

背景：Tavily 免费额度有限，且摘要带页面导航噪音（`博客园logo/搜索/订阅数`）。
重审「浏览器方案」时意外发现 **curl 直连 Bing 搜索页即可拿到结果**（headless
被反爬是浏览器指纹问题，不是线路问题——最朴素的 curl 反而畅通）。

排查过程（记录供后人参考）：
1. curl 带 UA 直连 `www.bing.com/search?q=...` → 10 条 `b_algo` 真实结果。
   Google 直连只有 JS 壳（无结果），需浏览器/Gemini Grounding。
2. **中文查询质量崩坏**（`今天杭州天气` → 日历网）：定位到本机 `daed.service`
   （eBPF 透明代理，出口台湾 HiNet `111.243.97.138`）+ 网络层面对 `cn.bing.com`
   的干扰（IPv4/IPv6 全 RST，与我们无关）。
3. **关键发现**：浏览器（第一条知乎/python doc）与脚本（第一条官网首页）
   结果不同 → 逐变量对照（cookie / IP / setlang / 参数矩阵）后确认缺一不可：
   **Firefox UA + 首页 cookie 会话 + `form=QBRE` 参数**。三者齐备后
   6/6 稳定返回高质量结果；偶发 SSL 断连（dae 线路抖动）由 Tavily 兜底。
4. 引擎策略定案：`prefer_engine` 默认 `"bing"`（Tavily 兜底），保留
   `"auto"` 按语言分流选项（中文走 Tavily）备用。

同时新增依赖 `beautifulsoup4`（HTML 结构解析，正则太脆）。

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
