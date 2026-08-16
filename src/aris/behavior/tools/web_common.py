"""web 工具共享逻辑：网页正文提取。

web_open / http_request 共用。trafilatura 提取正文（过滤导航/页脚/广告），
失败时用 BeautifulSoup .get_text() 兜底（简单 HTML / mock 页面场景）。
"""

from __future__ import annotations


def extract_page(html: str, url: str) -> str:
    """从 HTML 提取可读正文纯文本；两种提取器按序兜底，均失败返回空串。"""
    try:
        from trafilatura import extract

        body = extract(html, url=url)
        if body:
            return body.strip()
    except Exception:  # noqa: BLE001 —— 提取器失败换下一个
        pass
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in ("script", "style", "nav", "footer", "header", "aside"):
            for node in soup.find_all(tag):
                node.decompose()
        return soup.get_text("\n", strip=True).strip()
    except Exception:  # noqa: BLE001 —— 兜底也失败则返回空串
        return ""