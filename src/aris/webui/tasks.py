"""WebUI 后台任务登记表（内存态，供上传摄入等耗时任务轮询进度）。

为什么需要它：摄入要跑本地 embedding（CPU 密集型，批量时多核跑满），在请求线程里
同步跑会占住单 worker 的线程池、把整个管理后台拖住。故路由只登记任务并立即返回，
真正的活在 FastAPI BackgroundTasks（线程池）里跑，页面每秒轮询进度。

内存态是刻意的：管理后台重启即丢进度可接受，不值得为它引入持久层；只保留最近
``MAX_JOBS`` 条，避免长跑堆积。
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

MAX_JOBS = 20

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


@dataclass
class Job:
    """一个后台任务的状态。"""

    id: str
    kind: str
    status: str = STATUS_PENDING
    total: int = 0
    items: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    created_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        """转成可 JSON 化的字典（轮询接口直接返回）。"""
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "total": self.total,
            "done": len(self.items),
            "items": self.items,
            "error": self.error,
            "created_at": self.created_at,
        }


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def create(kind: str, total: int = 0) -> Job:
    """登记一个新任务（pending 态）。"""
    job = Job(id=uuid.uuid4().hex[:12], kind=kind, total=total)
    with _lock:
        _jobs[job.id] = job
        _trim_locked()
    return job


def get(job_id: str) -> Job | None:
    """按 id 取任务。"""
    with _lock:
        return _jobs.get(job_id)


def recent(limit: int = 5) -> list[Job]:
    """最近的任务（新→旧）。"""
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)
    return jobs[:limit]


def run(job_id: str, work: Callable[[], list[dict[str, Any]]]) -> None:
    """执行任务体（由 BackgroundTasks 调用）；异常收敛为 failed，不冒泡。"""
    job = get(job_id)
    if job is None:  # 已被裁剪/清理
        logger.warning(f"后台任务 {job_id} 不存在，跳过执行")
        return
    job.status = STATUS_RUNNING
    try:
        job.items = list(work())
    except Exception as exc:  # noqa: BLE001 —— 后台任务不能把异常抛到 UI
        logger.error(f"后台任务 {job_id} 失败：{exc}")
        job.status = STATUS_FAILED
        job.error = str(exc)
    else:
        job.status = STATUS_DONE
        logger.success(f"后台任务 {job_id} 完成（{len(job.items)} 项）")


def _trim_locked() -> None:
    """只保留最近 MAX_JOBS 条（调用方已持锁）。"""
    if len(_jobs) <= MAX_JOBS:
        return
    for old in sorted(_jobs.values(), key=lambda j: j.created_at)[: len(_jobs) - MAX_JOBS]:
        _jobs.pop(old.id, None)
