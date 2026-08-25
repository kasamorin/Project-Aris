"""登录限流——内存计数器，5 次失败锁 5 分钟。

单进程够用，重启清零（重启本身是运维操作）。不封 IP（LAN 环境）。
"""

from __future__ import annotations

import time


class LoginRateLimiter:
    """基于内存的登录限流器。"""

    def __init__(
        self,
        max_attempts: int = 5,
        window_seconds: float = 300.0,
        lockout_seconds: float = 300.0,
    ) -> None:
        self._max_attempts = max_attempts
        self._window = window_seconds
        self._lockout = lockout_seconds
        # ip → [attempt_timestamps]
        self._attempts: dict[str, list[float]] = {}

    def is_locked(self, ip: str) -> bool:
        """检查该 IP 是否被锁定。"""
        attempts = self._attempts.get(ip, [])
        # 清理窗口外的记录
        cutoff = time.time() - self._window
        attempts = [t for t in attempts if t > cutoff]
        self._attempts[ip] = attempts

        if len(attempts) >= self._max_attempts:
            last_attempt = attempts[-1]
            if time.time() - last_attempt < self._lockout:
                return True
            # 锁定期已过，清空记录
            self._attempts[ip] = []
        return False

    def record_failure(self, ip: str) -> None:
        """记录一次失败尝试。"""
        self._attempts.setdefault(ip, []).append(time.time())

    def reset(self, ip: str) -> None:
        """登录成功后清空该 IP 的失败记录。"""
        self._attempts.pop(ip, None)


# 全局限流器实例
login_limiter = LoginRateLimiter()
