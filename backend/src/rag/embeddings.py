"""
Embedding module for RAG pipeline.
Uses fastembed with bge-small-zh for Chinese text.
"""

import logging
import os
import sys
import threading
import zipfile
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# 国内镜像：优先 hf-mirror，失败后回退 modelscope
_MIRROR_ENDPOINTS = [
    "https://hf-mirror.com",
    "https://huggingface.mrdoge.com",
    "https://huggingface.com",
]

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


def _extract_bundled_model() -> None:
    """Extract embedding model from bundled zip if cache is empty.

    When distributed as a zip alongside the exe, extract it to the
    cache directory so fastembed can find it.
    """
    # Check if cache already has model (either HF hub format or GCS format)
    hf_marker = CACHE_DIR / "models--Qdrant--bge-small-zh-v1.5"
    gcs_marker = CACHE_DIR / "bge-small-zh-v1.5"
    if hf_marker.exists() or gcs_marker.exists():
        return

    # Find bundled model zip: next to exe, or next to data dir
    candidates = []
    if getattr(sys, "frozen", False):
        # PyInstaller bundle: exe is in install dir
        exe_dir = Path(sys.executable).parent
        candidates.append(exe_dir / "embedding-model.zip")
        # Also check data/vectors/cache relative to exe
        candidates.append(exe_dir / "data" / "embedding-model.zip")
    else:
        candidates.append(Path(__file__).parent.parent.parent / "embedding-model.zip")

    for zip_path in candidates:
        if zip_path.exists():
            logger.info("发现离线模型包: %s，正在解压...", zip_path)
            try:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(zip_path, "r") as zf:
                    for info in zf.infolist():
                        # Strip top-level directory (e.g. "model-cache/")
                        parts = Path(info.filename).parts
                        if len(parts) <= 1:
                            continue  # skip pure directory entries
                        stripped = str(Path(*parts[1:]))  # remove first dir
                        target = CACHE_DIR / stripped
                        if info.is_dir():
                            target.mkdir(parents=True, exist_ok=True)
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with zf.open(info) as src, open(target, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                logger.info("离线模型包解压完成")
                return
            except Exception as e:
                logger.warning("离线模型包解压失败: %s", e)

    logger.info("未找到离线模型包，将尝试在线下载")


def _download_model() -> TextEmbedding:
    """
    Download (if needed) and load the embedding model.
    Tries multiple HF mirrors for China mainland access.
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
            # 1. Try local cache first (model may have been pre-downloaded)
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

            # 1.5 Try extracting bundled model archive
            _extract_bundled_model()

            # 2. Try each mirror endpoint
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
