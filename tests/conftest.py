"""pytest 共享配置：全局静音 + 公共 fixture。

原根目录各测试脚本模块顶部反复做的两件事——静音 loguru、静音
notify.broadcast——收口到此处一次完成。公共 fixture 管理 mock 服务器的
生命周期与工具注册表。

注意：bus 服务级别的临时替换（如 web 迁移测试的 fake http.request）在各
测试文件内部自行负责恢复，不在此全局处理（保持 conftest 精简）。
"""

from __future__ import annotations

import sys
from typing import Iterator

import pytest
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="WARNING")

# 触发 aris.core 包导入（其 http 子模块导入即 provide http.request 服务），
# 保证 test_http_request.py 里走真实 call("http.request") 的用例可用。
import aris.core  # noqa: E402
import aris.core.llm.notify as notify  # noqa: E402

# 错误处理会广播桌面通知，测试里全局静音
notify.broadcast = lambda *a, **k: None  # noqa: E731

from aris.behavior.registry import ToolRegistry  # noqa: E402
from aris.behavior.tools.http_request import register as reg_http  # noqa: E402

from support.mock_http import MockHTTP  # noqa: E402
from support.mock_llm_server import MockLLMServer  # noqa: E402


@pytest.fixture
def llm_server() -> Iterator[MockLLMServer]:
    """干净的 mock LLM 端点：测试自行 register 场景，teardown 关闭。"""
    server = MockLLMServer().start()
    yield server
    server.stop()


@pytest.fixture
def http_server() -> Iterator[MockHTTP]:
    """本地 mock HTTP 服务（http_request 工具测试用）。"""
    server = MockHTTP().start()
    yield server
    server.stop()


@pytest.fixture
def http_registry() -> ToolRegistry:
    """注册了 http_request 工具的 ToolRegistry。"""
    reg = ToolRegistry()
    reg_http(reg)
    return reg
