"""知识库管理路由——文档列表、上传（后台摄入）、删除、重建索引、检索试验。

路由只做薄展示与表单转发，业务一律经总线 `knowledge.*`（同 webui 其他页面）。
上传走**后台任务 + 轮询**：摄入要跑本地 embedding（CPU 密集），不能在请求里同步跑，
否则单 worker 的管理后台会被拖住。
"""

from __future__ import annotations

from loguru import logger
from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from aris.core import call
from .. import tasks
from ..templates import render

router = APIRouter()

UPLOAD_ACCEPT = ".md,.markdown,.txt,.html,.htm"


def _safe_status() -> dict:
    """取知识库状态；数据库没起来时给出可读提示，而不是 500 或一串 psycopg 原文。"""
    try:
        status = call("knowledge.status") or {}
    except Exception as exc:  # noqa: BLE001 —— 管理后台宽容降级
        logger.warning(f"知识库状态查询失败：{exc}")
        return {"enabled": False, "error": _friendly_db_error(str(exc)), "docs": 0, "chunks": 0}
    if status.get("error"):
        status["error"] = _friendly_db_error(str(status["error"]))
    return status


def _friendly_db_error(message: str) -> str:
    """把连接类报错换成可操作的提示（便携实例不会随开机自启，属于常见状态）。"""
    markers = ("Connection refused", "connection failed", "could not connect")
    if any(m in message for m in markers):
        return "数据库未运行：在项目目录执行 `aris db start` 后刷新本页"
    return message


@router.get("/knowledge", response_class=HTMLResponse)
def knowledge_page(request: Request, q: str = "", top_k: int = 0) -> HTMLResponse:
    """知识库页面；带 q 参数时顺带做一次检索试验。

    刻意用同步 def：检索首次会加载本地模型（约 20s），走线程池不阻塞事件循环，
    否则 SSE 日志流与整站都会被卡住。
    """
    status = _safe_status()
    sources: list[dict] = []
    if status.get("enabled") and not status.get("error"):
        try:
            sources = call("knowledge.sources") or []
        except Exception as exc:  # 数据库不可用：页面照常显示，只是列表为空
            logger.warning(f"知识库列表查询失败：{exc}")
            status["error"] = str(exc)

    # 统一把连接类报错换成人话（status() 内部也会吞异常放进 error 字段）
    if status.get("error"):
        status["error"] = _friendly_db_error(str(status["error"]))

    results: list[dict] = []
    search_error = ""
    if q and status.get("enabled") and not status.get("error"):
        try:
            payload = call("knowledge.search", q, limit=top_k or None)
            results = payload.get("results", [])
        except Exception as exc:  # 检索失败只提示，不影响页面其余部分
            search_error = str(exc)
    return render(
        request,
        "knowledge.html",
        {
            "active_page": "knowledge",
            "status": status,
            "sources": sources,
            "jobs": [j.as_dict() for j in tasks.recent()],
            "query": q,
            "results": results,
            "search_error": search_error,
            "upload_accept": UPLOAD_ACCEPT,
        },
    )


@router.post("/knowledge/upload")
async def knowledge_upload(
    request: Request, background: BackgroundTasks, files: list[UploadFile] = File(default=[])
) -> RedirectResponse:
    """接收上传（异步读入内存）→ 登记任务 → 后台落盘并摄入。"""
    status = call("knowledge.status") or {}
    if not status.get("enabled"):
        return RedirectResponse("/knowledge", status_code=303)

    limit = int(status.get("max_file_bytes") or 0)
    payload: list[dict] = []
    rejected: list[dict] = []
    for upload in files:
        if not upload.filename:
            continue
        data = await upload.read()
        if limit and len(data) > limit:
            rejected.append(
                {
                    "path": upload.filename,
                    "status": "failed",
                    "chunks": 0,
                    "reason": f"超过 {limit // (1024 * 1024)}MB 上限",
                }
            )
            continue
        payload.append({"filename": upload.filename, "data": data})

    job = tasks.create("knowledge.upload", total=len(payload) + len(rejected))
    if rejected:
        job.items.extend(rejected)
    background.add_task(tasks.run, job.id, lambda: call("knowledge.upload", payload))
    return RedirectResponse(f"/knowledge?job={job.id}", status_code=303)


@router.get("/knowledge/jobs/{job_id}")
def knowledge_job(job_id: str) -> JSONResponse:
    """轮询任务进度（页面每秒拉一次）。"""
    job = tasks.get(job_id)
    if job is None:
        return JSONResponse({"id": job_id, "status": "unknown", "done": 0, "items": []})
    return JSONResponse(job.as_dict())


@router.post("/knowledge/remove")
def knowledge_remove(path: str = Form(...)) -> RedirectResponse:
    """移除一个文档及其块（软删）。"""
    try:
        call("knowledge.remove", path)
    except Exception as exc:  # noqa: BLE001 —— 失败不炸页面，状态区会显示原因
        logger.warning(f"移除文档失败：{exc}")
    return RedirectResponse("/knowledge", status_code=303)


@router.post("/knowledge/reindex")
def knowledge_reindex() -> RedirectResponse:
    """重建 HNSW 索引（幂等）。"""
    try:
        call("knowledge.reindex")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"重建索引失败：{exc}")
    return RedirectResponse("/knowledge", status_code=303)
