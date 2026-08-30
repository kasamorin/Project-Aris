"""WebUI 关键路径测试：auth 鉴权 / rate_limit 限流 / config 写回 / skills CRUD。

全部用 TestClient 走真实应用（含请求日志中间件 + AuthMiddleware + 总线服务
注册触发），不依赖外网。登录统一走 `_login`（follow_redirects=False）。

隔离策略（monkeypatch）：
- `ARIS_WEBUI_PASSWORD` 控制登录鉴权。
- `settings.data_dir`（get_settings 为 lru_cache 单例）+ `cfgtoml.config_dir`
  落到 tmp 目录，config 页写回与日志读目录不污染真实仓库。
- `core.llm.manage._providers_path` 指向 tmp providers.toml，提供商服务写回
  不碰真实 config/providers.toml。
- `behavior.skills.manager.SKILLS_DIR` 指向 tmp 技能目录（函数体内按模块全局
  名查找，patch 后 skills.* 服务即落到临时目录）。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from aris.webui import rate_limit


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """构造带登录、配置/数据全隔离的 webui 测试客户端。"""
    monkeypatch.setenv("ARIS_WEBUI_PASSWORD", "test-pass")
    monkeypatch.setattr(rate_limit.login_limiter, "_attempts", {})

    from aris.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    import aris.cfgtoml as cfgtoml
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cfgtoml, "config_dir", lambda: cfg_dir)

    import aris.core.llm.manage as manage
    providers_file = tmp_path / "providers.toml"
    shutil.copy(
        Path(__file__).resolve().parent.parent / "config" / "providers.toml",
        providers_file,
    )
    monkeypatch.setattr(manage, "_providers_path", lambda: str(providers_file))

    import aris.behavior.skills.manager as skills_mgr
    monkeypatch.setattr(skills_mgr, "SKILLS_DIR", tmp_path / "skills")

    from fastapi.testclient import TestClient
    from aris.webui import create_app

    with TestClient(create_app(), follow_redirects=False) as c:
        yield c


def _login(client, password: str):
    """提交一次登录（不跟随重定向）。"""
    return client.post("/login", data={"password": password})


# ---------- auth 鉴权 ----------

def test_unauth_redirects_to_login(client) -> None:
    """未登录访问受保护页面应 302 重定向到 /login。"""
    r = client.get("/")
    assert r.status_code == 302
    assert "/login" in r.headers["location"]


def test_login_wrong_password_no_session(client) -> None:
    """错误密码显示提示且不产生会话，后续仍应被重定向。"""
    r = _login(client, "wrong")
    assert r.status_code == 200
    assert "密码错误" in r.text
    assert client.get("/audit").status_code == 302


def test_login_success_grants_access(client) -> None:
    """登录成功后受保护页面可访问。"""
    assert _login(client, "test-pass").status_code == 303
    assert client.get("/").status_code == 200
    assert client.get("/providers").status_code == 200
    assert client.get("/config").status_code == 200


def test_static_is_public_without_login(client) -> None:
    """静态资源免鉴权；未登录也能直接拉取。"""
    r = client.get("/static/purify.min.js")
    assert r.status_code == 200


def test_forged_prefix_path_requires_auth(client) -> None:
    """/loginfoo 不得因 /login 的字符串前缀而绕过鉴权（历史漏洞回归）。"""
    assert client.get("/loginfoo").status_code == 302


# ---------- rate_limit 限流 ----------

def test_limit_locks_after_five_failures(client) -> None:
    """连续 5 次失败后锁定，提示登录尝试过多。"""
    for _ in range(5):
        _login(client, "wrong")
    assert "登录尝试过多" in _login(client, "wrong").text


def test_success_resets_failure_count(client) -> None:
    """登录成功后清空失败记录，后续失败不再立即触发锁定。"""
    for _ in range(4):
        _login(client, "wrong")
    assert _login(client, "test-pass").status_code == 303
    r = _login(client, "wrong")
    assert r.status_code == 200
    assert "密码错误" in r.text
    assert "登录尝试过多" not in r.text


# ---------- config 写回 ----------

def test_config_save_writes_whitelisted_keys(client, tmp_path: Path) -> None:
    """保存配置把可调字段写回 toml；白名单外键（如 evil_key）被丢弃。"""
    assert _login(client, "test-pass").status_code == 303
    r = client.post(
        "/config/save",
        data={"module": "chat", "temperature": "0.7", "evil_key": "x"},
    )
    assert r.status_code == 303
    toml_path = tmp_path / "config" / "chat.toml"
    assert toml_path.exists(), "应已写回 chat.toml"
    text = toml_path.read_text(encoding="utf-8")
    assert "temperature = 0.7" in text, text
    assert "evil_key" not in text, "白名单外键不应写入"


def test_config_save_rejects_module_traversal(client, tmp_path: Path) -> None:
    """module 不在白名单时弹回 /config，不得越界写出 .env.toml。"""
    assert _login(client, "test-pass").status_code == 303
    r = client.post(
        "/config/save",
        data={"module": "../../.env", "temperature": "0.5"},
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/config"
    assert not (tmp_path / ".env.toml").exists(), "穿越写入不得生效"


def test_config_escapes_special_strings(client, tmp_path: Path) -> None:
    """字符串值含引号/反斜杠/换行时转义，不破坏 toml 结构（历史漏洞回归）。"""
    assert _login(client, "test-pass").status_code == 303
    r = client.post(
        "/config/save",
        data={"module": "chat", "tool_result_preview_len": 'a"b\\c\n'},
    )
    assert r.status_code == 303, r.text[:200]
    text = (tmp_path / "config" / "chat.toml").read_text(encoding="utf-8")
    assert 'tool_result_preview_len = "a\\"b\\\\c\\u000A"' in text, text


# ---------- skills CRUD ----------

def test_skills_crud_full_path(client, tmp_path: Path) -> None:
    """技能创建/列表/详情/编辑/删除全链路走总线服务，全部命中临时目录。"""
    assert _login(client, "test-pass").status_code == 303

    skills_dir = tmp_path / "skills"
    assert not skills_dir.exists(), "初始应为空目录"

    # 创建技能
    r = client.post(
        "/skills/create",
        data={"name": "demo-skill", "description": "演示技能描述"},
    )
    assert r.status_code == 303, r.text[:200]
    assert (skills_dir / "demo-skill" / "SKILL.md").exists(), "应创建 SKILL.md"

    # 列表页出现该技能
    assert "demo-skill" in client.get("/skills").text

    # 详情页可读
    detail = client.get("/skills/demo-skill")
    assert detail.status_code == 200
    assert "演示技能描述" in detail.text

    # 编辑
    r = client.post(
        "/skills/demo-skill/edit",
        data={"content": "# demo-skill\n\n已编辑的内容\n"},
    )
    assert r.status_code == 303
    assert "已编辑的内容" in client.get("/skills/demo-skill").text

    # 删除，技能消失
    assert client.post("/skills/demo-skill/delete").status_code == 303
    assert not (skills_dir / "demo-skill").exists(), "删除应移除目录"
    assert "不存在" in client.get("/skills/demo-skill").text