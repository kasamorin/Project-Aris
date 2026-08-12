"""persona 模块 —— 人格系统（提示词工程起步）。

当前实现：把 Aris 的系统提示词收口到本模块，其他模块经统一通讯层
`core.call("persona.system_prompt")` 获取，不再各自硬编码人设文本。

演进方向（后续按需扩展）：
- 世界观 / 人际关系 / 成长轨迹的提示词组装
- 提示词工程 vs MCP 的实现方式之争（AGENTS.md 待定节）
"""

from ..core import provide
from .prompt import ARIS_SYSTEM_PROMPT


def _system_prompt() -> str:
    """返回 Aris 系统提示词。"""
    return ARIS_SYSTEM_PROMPT


# 注册为统一服务：任何模块经 call("persona.system_prompt") 取人设
provide("persona.system_prompt", _system_prompt)

__all__ = ["ARIS_SYSTEM_PROMPT"]
