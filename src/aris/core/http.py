"""core.http —— 统一 HTTP 通讯服务。

所有对外 HTTP 请求统一走 `core.call("http.request", ...)`，与 LLM 请求
（core/llm）同理：可审计（bus 自动记录每次调用）、可复用（任意模块 /
工具都能发请求）、统一默认头与超时。

设计要点：
- 只做传输（返回响应对象），语义（正文提取 / 解析）由调用方（工具）负责
- 默认浏览器 UA（部分站点对无 UA 请求 403）
- 不拦截私有地址（个人本机助手，允许访问内网服务，2026-08-15 定案）
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .bus import provide

# 默认浏览器 UA（与 web 抓取共用）
DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


@dataclass
class HttpResponse:
    """一次 HTTP 请求的响应（文本视图 + 元信息）。"""

    status: int
    text: str
    final_url: str
    content_type: str
    headers: dict[str, str] = field(default_factory=dict)


def request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: str | None = None,
    timeout: float = 20.0,
    follow_redirects: bool = True,
) -> HttpResponse:
    """发起一次 HTTP 请求，返回 HttpResponse。

    body 为原始字符串（调用方负责把对象序列化为 JSON）。
    """
    import httpx

    merged = {"User-Agent": DEFAULT_UA}
    if headers:
        merged.update(headers)
    with httpx.Client(timeout=timeout, follow_redirects=follow_redirects) as client:
        resp = client.request(method, url, headers=merged, content=body)
    return HttpResponse(
        status=resp.status_code,
        text=resp.text,
        final_url=str(resp.url),
        content_type=resp.headers.get("content-type", ""),
        headers=dict(resp.headers),
    )


# 注册为统一服务（core 包导入即生效）
provide("http.request", request)