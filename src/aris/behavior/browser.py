"""浏览器管理器：封装 Playwright Firefox 的生命周期。

联网搜索用 Playwright 自带的 Firefox（官方不支持驱动品牌版 Firefox，
见 AGENTS.md 已定案节）。浏览器实例会话内常驻：首次搜索时惰性启动，
会话结束后调用 close() 释放；独立干净 profile（data/firefox-profile/），
不碰用户日常 profile，无封号风险。

设计哲学落点：
- 职责单一：只管浏览器生命周期，搜索逻辑放 web_search.py
- 惰性启动：不搜索就不启动，避免白白占资源
- 宽容降级：启动失败抛出，由调用方（web_search）决定是否降级 Tavily
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright


class BrowserManager:
    """管理一个常驻的 Playwright Firefox 浏览器实例。

    线程安全性：Playwright 同步 API 对象不可跨线程使用，因此本类实例
    应只在 agent loop 所在线程内访问（工具执行就在该线程）。
    """

    def __init__(self, profile_dir: Path | str = Path("data/firefox-profile")) -> None:
        self._profile_dir = Path(profile_dir)
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
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._context = self._playwright.firefox.launch_persistent_context(
            user_data_dir=str(self._profile_dir),
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
