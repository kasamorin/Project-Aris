# serve 模块 —— 启动编排（`aris serve`）

> **状态：方案定案 + 首期已实现（2026-09-19）。**
> 本文是 serve 的唯一权威设计；商讨结论逐条落在下面，未定项标 `[待讨论]`。
> 首期实现范围见 §10「实现次序」（步骤 1–2 已完成，3–5 待做）。

## 1. 定位与边界（定案）

serve 是**组装根 + 启动编排**，相当于一次 `init`：把各模块按顺序拉起来，前台打印
日志与启动清单，`Ctrl-C` 收尾。它自己不做业务，只调用别人的启动动作。

明确边界：

- **单向**：serve 只**调用**别人的启动动作，**不对外提供查询/获取接口**——不注册
  `serve.status` 之类服务给别人读。谁要状态谁去问模块自己
  （`store.health` / `knowledge.status` / `llm.providers.load` …）。
- **非守护**：不做 daemonize / systemd / 后台化。前台运行，终端就是日志窗口；
  将来若真需要守护，由外部工具（systemd user unit / tmux）包裹，不写进代码。
- **不含 TUI 对话**：`aris chat` 独立（调试手段，且会和常驻服务抢终端）。
- **不做服务发现**：那是 CMCB 的事（`provide` / `call` / `has_service`）。

## 2. 「服务」分三类：不是所有模块都需要 start

| 类 | 模块 | 需要启动动作吗 |
|---|---|---|
| ① import 即就绪 | `core.llm`、`persona`、`behavior`（工具 / skills）、`http.request` | **不需要**——import 触发 `provide()` 即完成 |
| ② 需要外部资源 / 耗时 | `store`（PG 起没起、embedding 预热）、`knowledge`（迁移、索引、计数） | **需要**真实步骤 |
| ③ 入口 | `webui`（HTTP server）；将来 `voice`、平台适配 | 由 serve 决定是否拉起 |

所以 serve 不搞「每个模块都必须实现生命周期接口」的形式主义：①类模块不写任何 hook，
②③类模块各自 `provide("module.start", …)` / `provide("module.stop", …)`，
serve 侧只持一张**有序清单**逐个 `core.call`。

## 3. 启动顺序

固定有序清单（顺序可读优先于自动拓扑排序，够用且好调）：

| # | 步骤 | 动作 | 失败档位 |
|---|---|---|---|
| 0 | `services` | 核验各模块声明的依赖服务都已注册（缺一即 ERROR 且非零退出） | **required** |
| 1 | `core.llm` | import 触发注册；校验 `providers.toml` + 体检（缺 key / 无可用模型等） | optional |
| 2 | `persona` / `behavior` | import 触发注册（工具、skills 菜单） | optional |
| 3 | `store.db` | 探活；没跑则**自启**便携 PG；跑迁移到最新 | **required** |
| 4 | `store.embed` | **后台预热** embedding（就绪标志；见 §4） | optional |
| 5 | `knowledge` | 建表 / 建索引 / 统计文档与块数 | optional（依赖 3） |
| 6 | `webui` | 端口探测 → 起 HTTP（见 §4） | optional |

说明：探针是「只读 + 可失败」的体检（`aris doctor` 复用同一份），启动动作才是真正
拉东西；`--dry-run` 只跑前者。

终端输出形态（清单结构化，便于日志检索）：

```
aris serve v0.4.0  data=…/data  pid=12345
✓ core.llm     3 提供方，默认 deepseek-v4-flash-free
✓ persona      persona.system_prompt
✓ behavior     3 工具 / 4 skills
✓ store.db     PG 17.11 @127.0.0.1:55432（自启）
✓ store.embed  后台预热中（Bekko a25m，384 维）
✓ knowledge    1 文档 / 129 块，迁移已最新
✓ webui        http://127.0.0.1:9690（免鉴权模式：仅本机）
43 个总线服务全部就绪 · Ctrl-C 停止
```

预热完成后再补一行：`✓ store.embed  就绪（用时 21s）`。

## 4. 自启策略（定案）

### PG：默认自启，且**随 serve 一起停**

- 启动时探活：在跑 → 复用；没跑 → 走 `aris db start` 的等价调用（`bootstrap_env`）。
- **退出时只停「serve 自己拉起的」那个**：判据是 serve 启动前 `is_running()` 为假。
  本来就在跑的不动——避免把用户自己开的库停掉。
- 不注册系统服务、不后台常驻（沿用既有便携实例的运维约定）。
- **例外（已实现时补的规则）**：若本次没有任何常驻步骤（webui 未启用或被 `--skip`），
  serve 启动完就退出，此时**不执行收尾停止**——否则「起了又立刻停」等于白折腾，
  `aris serve --only store.db` 这种用法也会彻底没用。日志会说明库保持运行。

### embedding：启动即预热（后台 + 就绪标志）

- 理由：懒得等。本地模型加载约 20s，首个工具调用撞上会**顶穿我们设的 timeout**，
  而 serve 是长驻进程，模型迟早要加载。
- 形态：**后台线程预热，不阻塞清单打印**；就绪标志对外可查，检索侧若早于就绪
  **等待**而不是失败；就绪时日志补一行耗时。
- 开关：`preload_embedding`（配置 + `--no-preload`），默认开。首次下载模型
  2–3 分钟的进度展示属 `[待讨论]`。

### webui：默认并入，冲突则拒绝并不影响其他模块

- `aris serve` 默认拉起 WebUI；`aris web` **保留**（单起管理后台）。
- 启动前**端口探测** `host:port`：已被占用 → **拒绝启动 webui**，明确提示
  「端口 9690 已被占用，可能是另一个 `aris web` / `aris serve` 在运行」，
  **其余模块照常启动**，serve 不整体退出。
- `aris web` 同样加这道探测（解决「已有 web 在跑时又跑 `aris web`」的冲突）。
- 免鉴权模式（未配 `ARIS_WEBUI_PASSWORD` → 只绑回环）沿用既有护栏。

## 5. 失败分级与日志（定案）

- **两档**：`required`（`services` 服务表自检、`store.db`）与 `optional`（其余）。
- required 失败：依赖它的步骤跳过（knowledge → skipped），其余继续，**serve 不退出**；
  error 日志 + 清单标 `✗/–` + 结尾汇总「N 个模块降级，M 个跳过」。
- optional 失败：只影响自己，记 warning 后继续。
- **每一处降级、跳过、拒绝都要有日志**（error / warning），并附**可执行的下一步**
  （如「数据库未运行：在项目目录执行 `aris db start`」）。**严禁静默降级**——
  没写日志等于没做错误处理，日志也就没用了。

## 6. 调试选项与配置（定案）

CLI（默认全启）：

| 选项 | 作用 |
|---|---|
| `--only store,knowledge` | 白名单：只启动列出的步骤 |
| `--skip webui` | 黑名单：从集合里去掉 |
| `--dry-run` | 只做探针与清单打印，不实际启动任何东西 |

优先级：`--only` 先定集合 → `--skip` 再减 → **CLI 覆盖配置**。
不再加 `--no-db` / `--no-web` 之类的糖（等价于 `--skip db,webui`，KISS）。

`config/serve.toml`（模块级，加载方式同 `store/conf.py`）：

```toml
start_db = true            # 没跑就自启便携 PG
stop_db_on_exit = true     # 退出时停掉「自己拉起的」那个
preload_embedding = true   # 启动即后台预热 embedding
web_enabled = true         # 是否并入 WebUI
skip = []                  # 默认跳过的步骤（CLI --skip 追加）
```

WebUI 自身的 `host` / `port` / `session_days` 仍归 `config/webui.toml`；
serve 只管「启不启」。

## 7. 与既有入口 / 模块的关系（定案）

- **唯一组装根（已落地）**：`serve.assemble()` 是唯一一份「import 哪些所有者模块」
  的清单；服务自检由 `services` 步骤统一做。`aris serve` / `aris web` 都走它，
  测试在 `tests/conftest.py` 里调它，`webui.create_app()` 只搭 HTTP 层、不再自己
  import 各模块（原先 `cli.py` 与 `webui/__init__.py` 各维护一套，必然漂移）。
  依赖清单仍由各模块自己声明（如 `webui.REQUIRED_SERVICES`），避免「谁需要什么」
  的知识搬到 serve 里重新写一遍。
- `aris web` → 先 `serve.assemble()`，再跑 `webui` 那一步（端口探测也在其中）。
- `aris chat` → **纯前端，与 serve 互不干涉（2026-09-19 定案）**：既不自启也不被自启
  ——不触发 PG 自启、不触发 embedding 预热，只 import 自己需要的模块（保持现状的
  轻量组装）。理由：TUI 是随手敲的调试入口，不该为它等 20s 或改动系统状态。
- `aris doctor` → 环境自检（Python / C 扩展 / .env / 数据目录）+ `serve.probe_all()`，
  与 `aris serve --dry-run` 走同一条探针路径，保证体检结论与启动结论一致。
- **WebUI 仪表盘「系统状态区域」**（v0.3.0 遗留待办）→ WebUI 直接调各模块自己的
  服务取状态，**不经过 serve**（对应 §1 的单向边界）。

## 8. 与 BACKLOG 的接缝（现在不做）

- `#3 对外接口` / `#4 多人格并行` / `#7 自动任务`：将来都跑在 serve 里，serve 会是
  长驻宿主。**现在只做启动编排**，不加会话管理、不加调度器（YAGNI）。
- `#5 上下文压缩` / 记忆系统：与本模块无直接耦合。

## 9. 待定（勿替用户做决定）

- `[待讨论]` 未来多实例 / 多平台适配是否同进程（会直接决定 serve 的进程模型）
- `[待讨论]` 模型首次下载（2–3 分钟）的进度展示方式（是否透出 HF 下载进度）
- `[待讨论]` `--only` / `--skip` 是否也要覆盖「步骤内的子动作」（如只自启 PG 不跑迁移）

## 10. 实现次序与进度

| # | 内容 | 状态 |
|---|---|---|
| 1 | `serve/conf.py` + `config/serve.toml` + `aris serve`（清单与日志） | ✅ 2026-09-19 |
| 2 | 各模块补启动 hook（`store.start/stop`、`store.embed_preload`、`knowledge.start`、`webui.start/probe`） | ✅ 2026-09-19 |
| 3 | 端口探测 + 失败分级日志 + `--only/--skip/--dry-run` | ✅ 2026-09-19 |
| 4 | 上收组装根与依赖清单（`create_app()` 只搭 HTTP 层；`serve.assemble()` 唯一触发点；`services` 步骤统一核验 `REQUIRED_SERVICES`） | ✅ 2026-09-19 |
| 5 | 与 `aris doctor` 合流探针（`serve.probe_all()`；LLM 体检收敛为 `llm.providers.check` 总线服务） | ✅ 2026-09-19 |

首期落地（2026-09-19）：

- `src/aris/serve/{__init__,conf,steps}.py`——组装根（`assemble()`）、步骤表（探针 +
  启动动作）、编排（选步骤 / 依赖闭包 / 失败分级 / 清单 / 收尾）
- `core.bus.services()`：列出已注册服务（清单与自检用）
- store 侧新增 `store.start` / `store.stop` / `store.db_status` / `store.embed_preload`
  / `store.embed_status`，以及 `LocalBekkoProvider.warmup()`
- knowledge 侧新增 `knowledge.start`；webui 侧新增 `webui.probe` / `webui.start` 与
  `port_in_use()`（`aris web` 也走同一道端口探测）
- CLI 新增 `aris serve [--only] [--skip] [--dry-run]`；并把 serve / web 的控制台日志
  级别固定为 INFO——这两个命令的启动清单本身就是输出，被 WARNING 阈值吞掉就等于没有
- 测试：`tests/test_serve.py` 9 例（选择与依赖闭包、dry-run 只探针、optional/required
  失败分级、阻塞步骤延迟、真实步骤表结构、端口探测）

已知缺口（下一步）：

- **工具注册表 / agent loop / LLM engine / `skills.menu` 仍是会话级对象**（`ChatSession`
  里自建），serve 目前只做 import 级组装；将来做 BACKLOG #4/#7 时由 serve 持有单例
  （`behavior.start` 之类），届时该步骤才会有真实动作
- 退出细节仍 `[待讨论]`：二次 Ctrl-C 强杀、退出码明细
