"""
Embedding module for RAG pipeline.
Uses fastembed with bge-small-zh for Chinese text.
"""

import logging
import os
import sys
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

from fastembed import TextEmbedding  # noqa: E402
from ..utils.paths import VECTOR_DIR  # noqa: E402
from .bundled_models import extract_bundled_zip  # noqa: E402

# Model configuration
EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
EMBEDDING_DIM = 512  # bge-small-zh dimension

# Cache directory
CACHE_DIR = VECTOR_DIR / "cache"

# Bundled model identifiers
_EMBEDDING_ZIP = "embedding-model.zip"
_EMBEDDING_MODEL_DIR = "models--Qdrant--bge-small-zh-v1.5"

# Thread lock to prevent concurrent model downloads
_model_lock = threading.Lock()
_embedding_model: TextEmbedding | None = None
_model_error: Exception | None = None


# Mirror endpoints for online download
_MIRROR_ENDPOINTS = [
    "https://hf-mirror.com",
    "https://huggingface.mrdoge.com",
    "https://huggingface.com",
]


def _download_model() -> TextEmbedding:
    """
    Download (if needed) and load the embedding model.
    Tries offline bundle → local cache → online download.
    Thread-safe.
    """
    global _embedding_model, _model_error

    if _embedding_model is not None:
        return _embedding_model
    # Allow retries on new requests
    _model_error = None

    with _model_lock:
        if _embedding_model is not None:
            return _embedding_model

        try:
            # 1. Try bundled model (specific_model_path bypasses all cache logic)
            logger.info("检查离线模型包...")
            snapshot_path = extract_bundled_zip(
                zip_name=_EMBEDDING_ZIP,
                cache_dir=CACHE_DIR,
                model_dir_name=_EMBEDDING_MODEL_DIR,
                model_file="model_optimized.onnx",
            )
            if snapshot_path:
                logger.info("使用离线模型: %s", snapshot_path)
                model = TextEmbedding(
                    EMBEDDING_MODEL,
                    cache_dir=str(CACHE_DIR),
                    specific_model_path=str(snapshot_path),
                )
                list(model.embed(["test"]))
                logger.info("离线模型加载成功")
                _embedding_model = model
                return _embedding_model

            # 2. Try local cache (previously downloaded)
            logger.info("检查本地嵌入模型缓存...")
            try:
                model = TextEmbedding(
                    EMBEDDING_MODEL,
                    cache_dir=str(CACHE_DIR),
                    local_files_only=True,
                )
                list(model.embed(["test"]))
                logger.info("嵌入模型从本地缓存加载完成")
                _embedding_model = model
                return _embedding_model
            except Exception:
                logger.info("本地缓存无模型")

            # 3. Online download with mirror fallback
            last_err = None
            for endpoint in _MIRROR_ENDPOINTS:
                try:
                    os.environ["HF_ENDPOINT"] = endpoint
                    logger.info("尝试从 %s 下载模型...", endpoint)
                    model = TextEmbedding(
                        EMBEDDING_MODEL,
                        cache_dir=str(CACHE_DIR),
                        local_files_only=False,
                    )
                    list(model.embed(["test"]))
                    logger.info("嵌入模型从 %s 下载成功", endpoint)
                    _embedding_model = model
                    return _embedding_model
                except Exception as e:
                    logger.warning("从 %s 下载失败: %s", endpoint, e)
                    last_err = e
                    continue

            raise RuntimeError(
                f"嵌入模型下载失败（尝试了所有镜像源）。"
                f"请检查网络连接，或手动下载模型到: {CACHE_DIR}\n"
                f"最后错误: {last_err}"
            )

        except Exception as e:
            _model_error = e
            logger.error("嵌入模型加载失败: %s", e)
            raise


def get_embedding_model() -> TextEmbedding:
    """Get or create embedding model instance."""
    return _download_model()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a list of texts."""
    model = get_embedding_model()
    embeddings = list(model.embed(texts))
    return [e.tolist() for e in embeddings]


def embed_query(query: str) -> list[float]:
    """Generate embedding for a single query."""
    embeddings = embed_texts([query])
    return embeddings[0]
