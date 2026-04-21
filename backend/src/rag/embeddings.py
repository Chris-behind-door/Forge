"""
Embedding module for RAG pipeline.
Uses fastembed with bge-small-zh for Chinese text.
"""

import logging
import os
import threading

logger = logging.getLogger(__name__)

# 国内镜像：优先 hf-mirror，失败后回退 modelscope
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from fastembed import TextEmbedding  # noqa: E402
from ..utils.paths import VECTOR_DIR  # noqa: E402

# Model configuration
EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
EMBEDDING_DIM = 512  # bge-small-zh dimension

# Cache directory
CACHE_DIR = VECTOR_DIR / "cache"

# Thread lock to prevent concurrent model downloads
_model_lock = threading.Lock()
_embedding_model: TextEmbedding | None = None
_model_error: Exception | None = None


def _download_model() -> TextEmbedding:
    """
    Download (if needed) and load the embedding model.
    Uses hf-mirror.com for China mainland access.
    Thread-safe: concurrent callers will wait for the first to complete.
    """
    global _embedding_model, _model_error

    if _embedding_model is not None:
        return _embedding_model
    if _model_error is not None:
        raise _model_error

    with _model_lock:
        # Double-check after acquiring lock
        if _embedding_model is not None:
            return _embedding_model
        if _model_error is not None:
            raise _model_error

        try:
            logger.info("正在加载/下载嵌入模型 %s ...", EMBEDDING_MODEL)
            model = TextEmbedding(
                EMBEDDING_MODEL,
                cache_dir=str(CACHE_DIR),
                local_files_only=False,
            )
            # Trigger lazy initialization (downloads if needed)
            list(model.embed(["test"]))
            logger.info("嵌入模型加载完成")
            _embedding_model = model
            return _embedding_model
        except Exception as e:
            _model_error = e
            logger.error("嵌入模型加载失败: %s", e)
            raise


def get_embedding_model() -> TextEmbedding:
    """Get or create embedding model instance, waiting for download if in progress."""
    return _download_model()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for a list of texts.
    Blocks until model is downloaded and ready.
    """
    model = get_embedding_model()
    embeddings = list(model.embed(texts))
    return [e.tolist() for e in embeddings]


def embed_query(query: str) -> list[float]:
    """Generate embedding for a single query."""
    embeddings = embed_texts([query])
    return embeddings[0]
