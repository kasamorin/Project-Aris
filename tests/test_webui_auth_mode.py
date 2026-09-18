"""无密码模式（免鉴权）与监听地址护栏测试。

定案（2026-09-18）：未配置 ARIS_WEBUI_PASSWORD 时进入免鉴权模式（本机开发省事），
但监听地址会被降级为回环；配置了密码则行为与以前完全一致。
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def anon_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """不带密码的 WebUI 客户端（免鉴权模式）。"""
    monkeypatch.delenv("ARIS_WEBUI_PASSWORD", raising=False)

    from aris.config import get_settings

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path / "data")
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    from fastapi.testclient import TestClient

    from aris.webui import create_app

    with TestClient(create_app(), follow_redirects=False) as c:
        yield c


# ---------- 免鉴权模式 ----------


def test_passwordless_allows_direct_access(anon_client) -> None:
    """无密码时受保护页面直接可达，不再重定向到 /login。"""
    assert anon_client.get("/").status_code == 200
    assert anon_client.get("/knowledge").status_code == 200
    assert anon_client.get("/config").status_code == 200


def test_passwordless_login_redirects_home(anon_client) -> None:
    """无密码时 /login 没有意义：GET 直接回首页。"""
    r = anon_client.get("/login")

    assert r.status_code == 302
    assert r.headers["location"] == "/"


def test_passwordless_hides_logout_entry(anon_client) -> None:
    """导航不再显示「退出」，改为提示免鉴权模式。"""
    html = anon_client.get("/").text

    assert "免鉴权模式" in html
    assert 'href="/logout"' not in html


# ---------- 有密码时行为不变（对照） ----------


def test_password_still_required_when_configured(monkeypatch, tmp_path: Path) -> None:
    """配置了密码则维持原行为：未登录重定向到 /login。"""
    monkeypatch.setenv("ARIS_WEBUI_PASSWORD", "test-pass")

    from aris.config import get_settings

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path / "data")
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    from fastapi.testclient import TestClient

    from aris.webui import create_app

    with TestClient(create_app(), follow_redirects=False) as c:
        r = c.get("/")
        assert r.status_code == 302
        assert r.headers["location"] == "/login"


# ---------- 监听地址护栏 ----------


def test_resolve_bind_host_degrades_to_loopback_without_password(monkeypatch) -> None:
    monkeypatch.delenv("ARIS_WEBUI_PASSWORD", raising=False)
    from aris.webui.auth import resolve_bind_host

    host, warning = resolve_bind_host("0.0.0.0")
    assert host == "127.0.0.1"
    assert "ARIS_WEBUI_PASSWORD" in warning

    host, warning = resolve_bind_host("192.168.1.10")
    assert host == "127.0.0.1"
    assert warning


def test_resolve_bind_host_keeps_loopback_and_passworded_hosts(monkeypatch) -> None:
    from aris.webui.auth import resolve_bind_host

    monkeypatch.delenv("ARIS_WEBUI_PASSWORD", raising=False)
    host, warning = resolve_bind_host("127.0.0.1")
    assert (host, warning) == ("127.0.0.1", "")
    host, warning = resolve_bind_host("localhost")
    assert (host, warning) == ("localhost", "")

    monkeypatch.setenv("ARIS_WEBUI_PASSWORD", "test-pass")
    host, warning = resolve_bind_host("0.0.0.0")
    assert (host, warning) == ("0.0.0.0", "")
