"""本地 Bekko embedding（sentence-transformers + OpenVINO，CPU 推理）。

重依赖（sentence-transformers / optimum / openvino / torch）放在 **dependency-group
`embedding`**（`pyproject.toml`，默认安装；轻量环境可 `uv sync --no-default-groups`）。
本模块**懒加载**——只有真正调用时才 import 并加载模型，依赖缺失时抛出可读的
:class:`EmbeddingError`，主 CLI 不受影响。

模型缓存经 ``HF_HOME`` 指向项目内 ``data/models/``（data/ 不进 git），不散落到
``~/.cache/huggingface``。实测数据与选型见 developDoc/EMBEDDING.md。
"""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

from loguru import logger

from ..conf import get_store_config
from .base import EmbeddingError

DEFAULT_MODEL = "hotchpotch/bekko-embedding-v1-a25m"
OPENVINO_FILE = "openvino/openvino_model.xml"
BEKKO_A25M_DIM = 384


class LocalBekkoProvider:
    """本地 Bekko 提供方：进程内推理，常驻内存（约 1.5 GiB）。"""

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL,
        *,
        data_dir: Path | None = None,
        batch_size: int = 16,
        truncate_dim: int | None = None,
    ) -> None:
        self._model_id = model_id
        self._batch_size = batch_size
        self._truncate_dim = truncate_dim
        self._model = None  # 懒加载：首次 embed 才真正加载
        self._lock = Lock()
        self._hf_home = (Path(data_dir) if data_dir else _data_dir()) / "models"

    @property
    def name(self) -> str:
        """提供方标识。"""
        return f"local:{self._model_id.rsplit('/', 1)[-1]}"

    @property
    def dimension(self) -> int:
        """向量维度（截断时以截断维度为准）。"""
        return self._truncate_dim or BEKKO_A25M_DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量编码；空输入直接返回空列表（不加载模型）。"""
        if not texts:
            return []
        self._load()
        kwargs: dict[str, object] = {}
        if self._truncate_dim:
            kwargs["truncate_dim"] = self._truncate_dim
        try:
            vectors = self._model.encode(texts, batch_size=self._batch_size, **kwargs)
        except Exception as exc:  # 推理期异常统一转成可读错误
            raise EmbeddingError(f"本地 embedding 编码失败：{exc}") from exc
        return [[float(x) for x in vec] for vec in vectors]

    def _load(self) -> None:
        """加载模型（线程安全，只加载一次）。"""
        with self._lock:
            if self._model is not None:
                return
            self._prepare_env()
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise EmbeddingError(
                    f"本地 embedding 依赖不可用（{exc}）：请运行 uv sync 安装 embedding 组"
                ) from exc
            logger.info(f"加载本地 embedding 模型 {self._target()}（首次含下载需数分钟）...")
            try:
                self._model = SentenceTransformer(
                    self._target(),
                    backend="openvino",
                    device="cpu",
                    cache_folder=str(self._hf_home),
                    model_kwargs={"file_name": OPENVINO_FILE, "device": "CPU"},
                )
            except Exception as exc:
                raise EmbeddingError(f"加载模型 {self._model_id} 失败：{exc}") from exc
            logger.success(f"本地 embedding 就绪（{self.dimension} 维）")

    def _target(self) -> str:
        """模型来源：``data/models/<name>`` 下的本地目录优先，否则用 HF 仓库 id。"""
        local_dir = self._hf_home / self._model_id
        if local_dir.is_dir():
            return str(local_dir)
        return self._model_id

    def _prepare_env(self) -> None:
        """把 HF 缓存收进项目 data/（在 import/加载模型之前设置才生效）。"""
        self._hf_home.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("HF_HOME", str(self._hf_home))
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        # OpenVINO 默认往 HOME 写遥测文件；家里不可写时会刷一串 warning，直接关掉
        os.environ.setdefault("OV_TELEMETRY_OPT_OUT", "1")
        os.environ.setdefault("OPENVINO_TELEMETRY_OPT_OUT", "1")


def _data_dir() -> Path:
    """取全局配置里的数据目录（延迟 import，避免配置层反向依赖本模块）。"""
    from ...config import get_settings

    return Path(get_settings().data_dir)


def provider_from_config() -> LocalBekkoProvider:
    """按 `config/store.toml` 建本地提供方实例。"""
    cfg = get_store_config()
    return LocalBekkoProvider(
        cfg.local_model,
        batch_size=cfg.batch_size,
        truncate_dim=cfg.truncate_dim,
    )
