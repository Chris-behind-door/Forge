"""
Cross-encoder Reranker 模块

使用 sentence-transformers CrossEncoder 加载 bge-reranker-v2-m3。
延迟加载：首次调用时才加载模型。
支持离线模型包 + 镜像源回退。
"""

import logging
import os
import threading
from pathlib import Path

from ..utils.paths import VECTOR_DIR
from .bundled_models import extract_bundled_zip

logger = logging.getLogger(__name__)

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
# Limit HuggingFace timeouts to fail fast when offline
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "10")
os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "10")

RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"

# Bundled model identifiers
_RERANKER_ZIP = "reranker-model.zip"
_RERANKER_MODEL_DIR = "reranker"  # flat directory, not HF cache format

# Cache directory (shared with embedding)
CACHE_DIR = VECTOR_DIR / "cache"

_lock = threading.Lock()
_reranker_model = None
_load_error: Exception | None = None


def _load_reranker():
    """延迟加载 reranker 模型（线程安全）"""
    global _reranker_model, _load_error

    if _reranker_model is not None:
        return _reranker_model
    # Allow retries
    _load_error = None

    with _lock:
        if _reranker_model is not None:
            return _reranker_model

        try:
            from sentence_transformers import CrossEncoder

            logger.info("正在加载 Reranker 模型 %s ...", RERANKER_MODEL)

            # 1. Try bundled model (local path)
            snapshot_path = extract_bundled_zip(
                zip_name=_RERANKER_ZIP,
                cache_dir=CACHE_DIR,
                model_dir_name=_RERANKER_MODEL_DIR,
                model_file="model.safetensors",
            )
            if snapshot_path:
                logger.info("使用离线 Reranker 模型: %s", snapshot_path)
                model = CrossEncoder(str(snapshot_path), max_length=512, local_files_only=True)
                logger.info("离线 Reranker 模型加载完成")
                _reranker_model = model
                return _reranker_model

            # 2. Try offline cache
            saved_endpoint = os.environ.get("HF_ENDPOINT", "")
            try:
                os.environ["HF_HUB_OFFLINE"] = "1"
                model = CrossEncoder(RERANKER_MODEL, max_length=512)
                logger.info("Reranker 模型从本地缓存加载完成")
                _reranker_model = model
                return _reranker_model
            except Exception:
                logger.info("本地无 Reranker 模型缓存")
            finally:
                os.environ.pop("HF_HUB_OFFLINE", None)

            # 3. Try mirrors
            mirrors = [
                "https://hf-mirror.com",
                "https://huggingface.mrdoge.com",
            ]
            last_err = None
            for mirror in mirrors:
                os.environ["HF_ENDPOINT"] = mirror
                try:
                    model = CrossEncoder(RERANKER_MODEL, max_length=512)
                    logger.info("Reranker 模型从 %s 加载完成", mirror)
                    _reranker_model = model
                    return _reranker_model
                except Exception as e:
                    logger.debug("从 %s 加载 reranker 失败: %s", mirror, e)
                    last_err = e
                    continue

            # All mirrors failed
            logger.warning("Reranker 模型不可用，搜索将使用混合排序")
            _load_error = last_err or RuntimeError("Reranker 加载失败")
            raise _load_error

        except Exception as e:
            if e is not _load_error:
                _load_error = e
                logger.error("Reranker 模型加载失败: %s", e)
            raise


def rerank(query: str, texts: list[str], top_k: int | None = None) -> list[float]:
    """
    对 query-doc 对计算相关性分数

    Args:
        query: 查询文本
        texts: 文档文本列表
        top_k: 可选，只保留 top_k 个的分数（其余置 0）

    Returns:
        与 texts 等长的分数列表
    """
    if not texts:
        return []

    model = _load_reranker()

    pairs = [[query, t] for t in texts]
    scores = model.predict(pairs).tolist()

    if top_k is not None and top_k < len(scores):
        indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        result = [0.0] * len(scores)
        for rank, (idx, sc) in enumerate(indexed):
            if rank < top_k:
                result[idx] = sc
        return result

    return scores


def make_reranker_fn(top_k: int | None = None):
    """
    返回符合 scoring.py rank_candidates 签名的 reranker 函数

    签名: (query: str, texts: list[str]) -> list[float]
    """
    def _fn(query: str, texts: list[str]) -> list[float]:
        return rerank(query, texts, top_k=top_k)
    return _fn
