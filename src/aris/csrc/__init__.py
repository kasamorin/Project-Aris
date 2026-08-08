"""C 扩展占位 —— 通过 ctypes 按需加载编译产物。

使用前需先编译（可选步骤，见 demo.c 头部注释）：
    cc -shared -fPIC -O2 -o demo.so demo.c
未编译 / 加载失败时自动降级，不影响主包运行。
"""

import ctypes
from pathlib import Path

_LIB_FILE = Path(__file__).parent / "demo.so"


def _load_lib() -> ctypes.CDLL | None:
    """加载 demo.so，失败返回 None（外围降级）。"""
    if not _LIB_FILE.exists():
        return None
    try:
        lib = ctypes.CDLL(str(_LIB_FILE))
        lib.aris_demo_add.restype = ctypes.c_int64
        lib.aris_demo_add.argtypes = [ctypes.c_int64, ctypes.c_int64]
        return lib
    except OSError:
        return None


_lib = _load_lib()


def demo_available() -> bool:
    """C 扩展是否可用。"""
    return _lib is not None


def demo_add(a: int, b: int) -> int:
    """调用 C 示例函数；未编译时降级为 Python 计算。"""
    if _lib is None:
        return a + b
    return int(_lib.aris_demo_add(a, b))
