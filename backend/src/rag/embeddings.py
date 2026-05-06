"""
Embedding module for RAG pipeline.
Uses fastembed with bge-small-zh for Chinese text.
"""

import logging
import os
import shutil
import sys
import threading
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

from fastembed import TextEmbedding  # noqa: E402
from ..utils.paths import VECTOR_DIR  # noqa: E402

# Model configuration
EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
EMBEDDING_DIM = 512  # bge-small-zh dimension

# Cache directory
CACHE_DIR = VECTOR_DIR / "cache"

# Bundled model snapshot directory name (inside the zip)
_MODEL_SNAPSHOT_DIR = "models--Qdrant--bge-small-zh-v1.5"

# Thread lock to prevent concurrent model downloads
_model_lock = threading.Lock()
_embedding_model: TextEmbedding | None = None
_model_error: Exception | None = None


def _find_extracted_snapshot() -> Path | None:
    """Find the extracted model snapshot directory (contains model_optimized.onnx)."""
    marker = CACHE_DIR / _MODEL_SNAPSHOT_DIR / "snapshots"
    if not marker.exists():
        return None
    for snap in marker.iterdir():
        if snap.is_dir() and (snap / "model_optimized.onnx").exists():
            return snap
    return None


def _extract_bundled_model() -> Path | None:
    """Extract embedding model from bundled zip if not already extracted.

    Returns the snapshot path if successful, None otherwise.
    """
    # Already extracted and valid?
    existing = _find_extracted_snapshot()
    if existing:
        logger.info("模型已存在于: %s", existing)
        return existing

    # Clean up any leftover partial extraction
    partial = CACHE_DIR / _MODEL_SNAPSHOT_DIR
    if partial.exists():
        logger.info("清理不完整的模型目录: %s", partial)
        shutil.rmtree(partial, ignore_errors=True)

    # Find bundled model zip
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        candidates.append(exe_dir / "embedding-model.zip")
        candidates.append(exe_dir / "data" / "embedding-model.zip")
    else:
        candidates.append(Path(__file__).parent.parent.parent / "embedding-model.zip")

    for zip_path in candidates:
        if zip_path.exists():
            logger.info("发现离线模型包: %s，正在解压...", zip_path)
            try:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(zip_path, "r") as zf:
                    # Detect if zip has a single top-level wrapper dir
                    top_dirs = set()
                    for info in zf.infolist():
                        parts = Path(info.filename).parts
                        if parts:
                            top_dirs.add(parts[0])
                    should_strip = len(top_dirs) == 1 and top_dirs.pop() not in ("models--",)
                    # Check if the single top dir is NOT the model dir itself
                    should_strip = len(top_dirs) == 1
                    top_name = list(top_dirs)[0] if top_dirs else ""
                    # Don't strip if the top dir IS the model dir
                    if top_name.startswith("models--"):
                        should_strip = False

                    logger.info("zip顶层目录: %s, strip=%s", top_name, should_strip)

                    for info in zf.infolist():
                        parts = Path(info.filename).parts
                        if not parts:
                            continue
                        if should_strip and len(parts) > 1:
                            rel = str(Path(*parts[1:]))
                        else:
                            rel = info.filename
                        if not rel:
                            continue
                        target = CACHE_DIR / rel
                        if info.is_dir():
                            target.mkdir(parents=True, exist_ok=True)
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with zf.open(info) as src, open(target, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                logger.info("离线模型包解压完成")

                snapshot = _find_extracted_snapshot()
                if snapshot:
                    logger.info("模型快照目录: %s", snapshot)
                    onnx_file = snapshot / "model_optimized.onnx"
                    logger.info("ONNX文件: %s (存在=%s, 大小=%s)", onnx_file, onnx_file.exists(), onnx_file.stat().st_size if onnx_file.exists() else 'N/A')
                    return snapshot
                logger.warning("解压完成但未找到模型快照目录")
            except Exception as e:
                logger.warning("离线模型包解压失败: %s", e)

    logger.info("未找到离线模型包")
    return None


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
    # Don't cache errors permanently - allow retries on new requests
    # (e.g. user might fix network or add model files between attempts)

    with _model_lock:
        if _embedding_model is not None:
            return _embedding_model
        # Reset error on retry
        _model_error = None

        try:
            # 1. Try bundled model (specific_model_path bypasses all cache logic)
            logger.info("检查离线模型包...")
            snapshot_path = _extract_bundled_model()
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
