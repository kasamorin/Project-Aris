# TUI 四个已知问题的修复记录（2026-08-09 起）

> **本文件为临时工作文档：四个问题全部解决并验证通过后，删除本文档。**
> 届时把最终结论整理进 `PROGRESS.md` / 相关代码注释即可，不留重复文档。

本文档单独记录 `aris chat` TUI 四个已知问题的**现象、根因、修复方案、
当前进度、验证方法**，供中断后快速恢复工作。相关代码全部在
`src/aris/chat/tui.py`（界面 + 键绑定）、`src/aris/behavior/browser.py`
（浏览器/Playwright 生命周期）。

问题清单：

| # | 问题 | 状态 |
|---|---|---|
| 1 | 运行 `aris chat` 偶发 Node.js EPIPE 崩溃 | 已修复（待真机验证） |
| 2 | TUI 状态行覆盖已输出的文字 | 已修复（待真机验证） |
| 3 | Shift+Enter 插入「OM」而非换行 | 已修复（待真机验证） |
| 4 | TUI 无法选中/复制文本 | 已修复（待真机验证） |

---

## 问题 1：运行 `aris chat` 偶发 Node.js EPIPE 崩溃

### 现象

运行 `uv run aris chat` 时（启动阶段），终端打印 Node.js 崩溃栈：

```
node:events:487
      throw er; // Unhandled 'error' event
      ^

Error: write EPIPE
    at WriteWrap.onWriteComplete [as oncomplete] (node:internal/stream_base_commons:87:19)
...
errno: -32, code: 'EPIPE', syscall: 'write'
Node.js v24.18.1
```

### 根因分析（当前认知）

- 报错是 **Node.js 进程**的未处理 'error' 事件，EPIPE 表示向已关闭的管道写入。
- Aris 项目里唯一的 Node.js 进程来源是 **Playwright 的 driver**（playwright 的
  sync API 通过子进程 node driver 与浏览器通信）。
- 关键判断：普通 `aris chat` 启动路径**不应触发浏览器**——`ChatSession.__init__`
  只 `BrowserManager(profile_dir=...)` 创建对象（惰性，`start()` 才真正启动），
  见 `src/aris/chat/session.py:106`。且 `uv run` 本身不涉及 node。
- 因此最可能是**上次会话残留的 Playwright driver 进程**：以前测试时用
  `kill -9` 强杀过 aris 进程，Playwright 的 node driver 成为孤儿进程，
  其管道断裂后写入时报 EPIPE，错误打到终端。
- 已做环境检查（2026-08-09）：`ps aux` 未见残留 playwright/node 进程，
  但 `data/firefox-profile/` 有上次 Playwright Firefox 留下的 profile 数据
  （activity-stream 等缓存），说明浏览器确实跑过且被杀残留过。

### 修复方案（已实现）

1. **进程清理**：新增 `cleanup_stale_browser_processes()`（`behavior/browser.py`），
   按「当前环境 playwright driver 路径 + 本 profile 目录」精确匹配残留的
   孤儿 driver / Firefox 进程并 `SIGKILL`，随后移除 profile 锁文件。
   在 `BrowserManager.start()` 与 `ChatSession.__init__` 两个时点调用，
   保证 EPIPE 噪音与 profile 锁问题都不出现。精确匹配不误杀其他环境的
   playwright；失败静默降级（pgrep 不可用如 Termux 时放弃）。
2. **保险性清理**：`BrowserManager.close()` 已幂等且吞异常，TUI 的 `run()`
   已在 `finally` 里调 `session.close()` 确保 `playwright.stop()` 一定执行。

### 验证方法（下次复现时做）

- `ps aux | rg -i "playwright|firefox.*profile|node"` 看有无残留进程；
- `ls data/firefox-profile/` 看是否有锁文件（`.parentlock` 等）；
- 连续多次启动退出 `aris chat`，看 EPIPE 是否出现；
- 若有残留 driver，`kill` 掉后再次启动看是否消失，即可确认根因。

### 当前进度

- 2026-08-09 已记入 PROGRESS.md 已知问题节。
- **已实现清理逻辑**（browser.py / session.py / behavior __init__）。
- 当前环境为远程无显示器（ssh 接入），**无法真机验证，待回到 Arch 桌面验证**。

---

## 问题 2：TUI 状态行覆盖已输出的文字

### 现象

模型在调用工具前先输出了文字（例如「我搜一下」），随后工具调用提示
`[调用工具: web_search]` 会把**已输出的那行文字覆盖掉**。且工具调用完
成后，后续输出紧跟同一行、无空格。

### 根因分析（已定位）

`src/aris/chat/tui.py` 的状态行模型：

- `_start_generation` 里 `_append_output(PROMPT_ARIS)`（即 `Aris: `），并记录
  `_state_start = len(self._output_text)`，`_state_active = True`。
- `_consume` 收到内容 delta 时调 `_clear_state_line()`：把 `_output_text`
  截断回 `_state_start`（保留 `Aris: ` 前缀）再追加内容。
- `_consume` 收到 `ToolNotice` 时调 `_show_tool(name)`，旧实现里**无条件**
  执行 `_render_state_line()`，而 `_render_state_line` 也是把 `_output_text`
  截断到 `_state_start` 再拼 spinner + 工具名。

于是：模型先输出「我搜一下」→ 内容已写入 `_output_text` → 工具通知到达 →
`_show_tool` 截断回 `_state_start`，「我搜一下」被抹掉。

### 修复方案（已实现一半）

`_show_tool` 改为**区分两种情形**：

```python
def _show_tool(self, name: str) -> None:
    """工具调用提示。

    仍在等待首字（状态行活跃）时，把工具名显示到状态行同行；
    已有内容输出（状态行已清除）时，另起一行显示，避免覆盖已输出的文字。
    """
    if self._state_active:
        self._tool_name = name
        self._render_state_line()
    else:
        self._append_output(f"\n  [调用工具: {name}]\n")
```

要点：
- 状态行活跃（`_state_active`）意味着**还没输出任何内容**，此时同行显示
  工具名是安全的（后续首个 delta 会 `_clear_state_line` 清掉）。
- 状态行已被清除（`_state_active == False`）意味着**内容已经开始输出**，
  此时工具提示应另起一行追加，绝不截断已有内容。

### 剩余工作

- 检查 `_consume` 中内容 delta 与 ToolNotice 的时序：`_clear_state_line()`
  在首个 delta 到达时把 `_state_active` 置 False，之后的工具通知自然走
  「另起一行」分支，逻辑自洽。
- 需验证「调用完输出无空格」是否也一并解决（新增的 `[调用工具: 名称]` 行
  自带前后换行，内容从新行开始，不存在紧贴问题）。

### 验证方法

- 用 `test_tui_issue2.py`（仓库根目录临时脚本）mock 返回「先文本增量，再
  工具调用，再文本增量」，观察 TUI 输出：`Aris: 我搜一下` 不应被覆盖，
  工具提示应另起一行。已通过。
- 也可直接真实模型问一个会先说话再调工具的问题。

### 当前进度

- 2026-08-09 已修改 `tui.py` 的 `_show_tool`（上面的代码已写入）。
- 脚本级验证已通过（`test_tui_issue2.py`）。
- 当前环境为远程无显示器（ssh 接入），**无法真机验证，待回到 Arch 桌面验证**。

---

## 问题 3：Shift+Enter 换行失效，插入「OM」

### 现象

输入框里按 Shift+Enter 本应换行，实际插入了「OM」两个字符。

### 根因分析（已实测确认）

- 当前绑定的是 CSI-u 序列 `ESC[13;2u`：
  ```python
  @kb.add("escape", "[", "1", "3", ";", "2", "u")
  ```
- 实测当前终端实际发送的是 **SS3 应用键序列 `ESC O M`**，不是 CSI-u。
- 用 prompt_toolkit 的 `Vt100Parser` 实测解析结果：

  ```
  SS3 ESC O M:      [('Escape', '\x1b'), ('O', 'O'), ('M', 'M')]
  CSI-u ESC[13;2u:  [('Escape', '\x1b'), ('[', '['), ('1', '1'), ...]
  ESC 单独:         [('Escape', '\x1b')]
  ```

  即 `ESC O M` 被解析成 `Escape` + `O` + `M` 三个独立按键，现有绑定不匹配，
  于是 `O`、`M` 被当作普通字符插入输入框 → 出现「OM」。

### 修复方案

在 `_build_key_bindings` 里**新增 SS3 绑定**，与 CSI-u 绑定并存：

```python
@kb.add("escape", "[", "1", "3", ";", "2", "u")  # CSI-u（kitty/wezterm/foot）
@kb.add("escape", "O", "M")                      # SS3（本机实测）
def _shift_enter(event) -> None:
    event.current_buffer.insert_text("\n")
```

注意：prompt_toolkit 的 key binding 用小写 `"escape"`，后面的 `O`、`M` 是
大写字符（SS3 序列是 `ESC O M`，O 和 M 都是大写）。需要确认大小写匹配
（KeyBindings 里字符是大小写敏感的，测试时以 `("O", "O")` 形式解析出来
对应 `"O"`）。Alt+Enter（`escape c-m`）兜底保留。

### 验证方法

- 启动 `aris chat`，按 Shift+Enter，确认输入框换行而不是出现「OM」。
- 继续保留 CSI-u 绑定，确认 kitty 等终端下也正常（两种绑定互不冲突）。

### 当前进度

- 根因已实测确认（解析结果见上），修复代码**已写入**（`escape O M` 绑定
  已加，与 CSI-u 并存）。
- 当前环境为远程无显示器（ssh 接入），**无法真机验证，待回到 Arch 桌面验证**。

---

## 问题 4：TUI 无法选中/复制文本

### 现象

全屏 TUI 里鼠标无法像普通终端那样选中/复制输出区文本——点击被当作光标
定位。

### 根因分析（已确认）

- `Application(mouse_support=True)` 开启鼠标跟踪后，终端把鼠标事件全部
  交给应用，系统级文本选择被拦截。
- 已确认 prompt_toolkit 的鼠标事件解析**区分修饰符**：`xterm_sgr_mouse_events`
  里有 `SHIFT`、`ALT`、`CONTROL` 组合（如 `(4, "m")` → left_up + SHIFT）。
  即：**按住 Shift 的鼠标操作会带 SHIFT 修饰符**，可以据此区分
  「系统选中（带 Shift） vs 应用内操作（不带 Shift）」。

### 修复方案（已定案：方案 1，Shift+鼠标放行）

在 `_build_key_bindings` 中新增自定义 `Keys.Vt100MouseEvent` 绑定。由于
merge 顺序是 `[load_key_bindings(), 自定义 kb]`，且 prompt_toolkit 取
`matches[-1]`（最后一个匹配的绑定）执行，自定义绑定必然接管所有鼠标事件。

处理逻辑（`tui.py`）：
- 用 `_is_shift_mouse(event.data)` 解析 SGR 序列 `CSI<b;x;yM`，`b & 4`
  为 SHIFT 修饰位（对照 `xterm_sgr_mouse_events` 表）。
- 带 SHIFT：`return NotImplemented`，不触发光标定位/滚动，放行给系统选中。
- 不带 SHIFT：委托模块级 `_DEFAULT_MOUSE_HANDLER`（从
  `load_mouse_bindings()` 提取的默认处理器），保持原有点击定位/滚动。

**关键认知**：prompt_toolkit 一旦开启 mouse tracking，无论应用 handler
返回什么，鼠标事件都会被消费、无法真正"交回"终端。真正的放行机制在
**终端侧**——多数现代终端（含 konsole）在按住 Shift 时临时禁用 mouse
reporting，事件根本不发给应用，由终端自己做系统选中。因此：
- 对 konsole：Shift+拖拽天然放行，无需应用参与；本修复是兜底保障。
- 对其他仍上报 Shift 事件的终端：应用忽略该事件、不误定位光标，
  但系统选中仍需终端配合。

### 验证方法

- 脚本级验证：SGR 修饰位解析（`\x1b[<4;1;1M`→True、`\x1b[<0;1;1M`→False、
  拖动+Shift `\x1b[<36;...`→True、滚轮 `\x1b[<64;...`→False）；
  merge 后自定义绑定为 `matches[-1]`（接管）。已通过。
- 真机验证（待用户）：konsole 跑 `aris chat`，按住 Shift 拖动鼠标选中
  输出区文本 → Ctrl+Shift+C 复制，确认可行。

### 当前进度

- **已实现方案 1**（自定义鼠标绑定 + SHIFT 放行），脚本级验证通过。
- 当前环境为远程无显示器（ssh 接入），**真机验证待回到 Arch 桌面 konsole
  实测**：按住 Shift 拖动选中输出区文本 → Ctrl+Shift+C 复制。

---

## 当前工作区状态

- 四个问题修复代码均已写入，待真机验证（当前远程无显示器无法跑）。
- 改动文件：`src/aris/chat/tui.py`（问题 2/3/4）、`src/aris/behavior/browser.py`
  与 `src/aris/behavior/__init__.py`、`src/aris/chat/session.py`（问题 1）、
  `PROGRESS.md`、本文档。
- 临时验证脚本：`test_kb.py`、`test_tui_issue2.py`（仓库根目录，验证通过后
  可删除；已于 2026-08-15 清理）。

## 恢复工作的步骤

1. 回到 Arch 桌面，真机验证四个问题（Shift+Enter 换行、工具调用提示不覆盖、
   Shift+鼠标选中、多次启停无 EPIPE）。
2. 全部通过后：删除本文件、删除临时测试脚本，整理结论到 `PROGRESS.md`。
