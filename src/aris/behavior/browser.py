"""浏览器管理器：封装 Playwright Firefox 的生命周期。

联网搜索用 Playwright 自带的 Firefox（官方不支持驱动品牌版 Firefox，
见 AGENTS.md 已定案节）。浏览器实例会话内常驻：首次搜索时惰性启动，
会话结束后调用 close() 释放；独立干净 profile（data/firefox-profile/），
不碰用户日常 profile，无封号风险。

设计哲学落点：
- 职责单一：只管浏览器生命周期，搜索逻辑放 web_search.py
- 惰性启动：不搜索就不启动，避免白白占资源
- 宽容降级：启动失败抛出，由调用方（web_search）决定是否降级 Tavily
- 启动前清理上次强杀（kill -9）残留的 Playwright 孤儿进程，
  避免其写入已断裂管道时产生 EPIPE 崩溃噪音、以及 profile 被锁
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright


def _playwright_driver_path() -> str:
    """取当前环境下 playwright driver 目录的绝对路径，用于进程精确匹配。"""
    import inspect

    import playwright

    return str((Path(inspect.getfile(playwright)).parent / "driver").resolve())


def cleanup_stale_browser_processes(profile_dir: Path | str) -> None:
    """清理上次异常退出残留的 Playwright 孤儿进程与 profile 锁。

    触发场景：会话期间用过浏览器后被强杀（kill -9），Playwright 的
    node driver 与 Firefox 会残留为孤儿进程——driver 向已断裂的管道
    写入时报 EPIPE（表现为终端出现 Node.js 崩溃栈），Firefox 还占用
    profile 锁导致下次启动失败。本函数按特征精确匹配本项目的进程
    （当前环境的 playwright driver 路径 + 本 profile 目录），不误杀
    其他环境的 playwright；尽力清理，失败静默降级。在 chat 会话启动
    与浏览器启动两个时点都会调用，保证噪音不出现。
    """
    profile = str(Path(profile_dir).resolve())
    driver_dir = _playwright_driver_path()
    try:
        proc = subprocess.run(
            ["pgrep", "-a", "-f", "."],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return  # pgrep 不可用（如 Termux）或超时：放弃清理
    for line in proc.stdout.splitlines():
        pid_s, _, cmd = line.partition(" ")
        if not pid_s.isdigit():
            continue
        # 只处理本项目的进程：当前环境的 playwright driver，或占用本 profile 的 firefox
        is_driver = "run-driver" in cmd and driver_dir in cmd
        is_ours = "firefox" in cmd and profile in cmd
        if not (is_driver or is_ours):
            continue
        try:
            os.kill(int(pid_s), signal.SIGKILL)
        except (OSError, ValueError):
            pass
    # 移除残留的 profile 锁文件（此时对应进程已被杀，锁必然失效）
    for name in (".parentlock", "lock", "SingletonLock", "SingletonCookie"):
        try:
            p = Path(profile_dir) / name
            if p.exists() or p.is_symlink():
                p.unlink(missing_ok=True)
        except OSError:
            pass


class BrowserManager:
    """管理一个常驻的 Playwright Firefox 浏览器实例。

    线程安全性：Playwright 同步 API 对象不可跨线程使用，因此本类实例
    应只在 agent loop 所在线程内访问（工具执行就在该线程）。
    """

    def __init__(self, profile_dir: Path | str = Path("data/firefox-profile")) -> None:
        self.profile_dir = Path(profile_dir)
        self._playwright = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def start(self) -> None:
        """启动浏览器（惰性：已启动则直接复用）。

        使用持久化 context（user_data_dir），把 cookie 等状态落在独立
        profile 目录里，多次搜索间状态可复用。
        """
        if self._context is not None:
            return
        cleanup_stale_browser_processes(self.profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._context = self._playwright.firefox.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            headless=True,
        )
        self._page = self._context.new_page()

    @property
    def page(self) -> Page:
        """当前页面；未启动则先启动。"""
        if self._page is None:
            self.start()
        return self._page  # type: ignore[return-value]

    @property
    def is_started(self) -> bool:
        """浏览器是否已启动（用于判断是否需要降级）。"""
        return self._context is not None

    def close(self) -> None:
        """关闭浏览器并释放资源（幂等，可多次调用）。"""
        try:
            if self._context is not None:
                self._context.close()
        except Exception:
            pass  # 关闭失败不阻塞会话退出
        finally:
            self._context = None
            self._page = None
            if self._playwright is not None:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
