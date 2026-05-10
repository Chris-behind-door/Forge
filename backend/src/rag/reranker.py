"""
Cross-encoder Reranker 模块

使用 transformers 原生 AutoModelForSequenceClassification 加载 bge-reranker-v2-m3。
延迟加载：首次调用时才加载模型。
支持离线模型包 + HF cache + 镜像源回退。

注：不用 sentence_transformers.CrossEncoder（5.x 版本 OOM 问题严重）。
"""

import logging
import os
import threading

from ..utils.paths import VECTOR_DIR

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

MAX_LENGTH = 512

_lock = threading.Lock()
_reranker_model = None
_reranker_tokenizer = None
_load_error: Exception | None = None


def _detect_device() -> str:
    """检测最佳推理设备"""
    import torch
    if torch.cuda.is_available():
        device = "cuda:0"
        logger.info("Reranker 使用 GPU: %s", torch.cuda.get_device_name(0))
        return device
    logger.info("Reranker 使用 CPU")
    return "cpu"


def _load_reranker():
    """延迟加载 reranker 模型和 tokenizer（线程安全）"""
    global _reranker_model, _reranker_tokenizer, _load_error

    if _reranker_model is not None:
        return _reranker_model, _reranker_tokenizer
    # Allow retries
    _load_error = None

    with _lock:
        if _reranker_model is not None:
            return _reranker_model, _reranker_tokenizer

        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            import torch

            logger.info("正在加载 Reranker 模型 %s ...", RERANKER_MODEL)

            # Detect device
            device = _detect_device()

            # 1. Try bundled model (local path)
            snapshot_path = extract_bundled_zip(
                zip_name=_RERANKER_ZIP,
                cache_dir=CACHE_DIR,
                model_dir_name=_RERANKER_MODEL_DIR,
                model_file="model.safetensors",
            )
            if snapshot_path:
                logger.info("使用离线 Reranker 模型: %s", snapshot_path)
                tokenizer = AutoTokenizer.from_pretrained(str(snapshot_path), local_files_only=True)
                model = AutoModelForSequenceClassification.from_pretrained(
                    str(snapshot_path), local_files_only=True,
                )
                model.to(device).eval()
                logger.info("离线 Reranker 模型加载完成 (device=%s)", device)
                _reranker_model = model
                _reranker_tokenizer = tokenizer
                return _reranker_model, _reranker_tokenizer

            # 2. Try offline cache
            try:
                os.environ["HF_HUB_OFFLINE"] = "1"
                tokenizer = AutoTokenizer.from_pretrained(RERANKER_MODEL, local_files_only=True)
                model = AutoModelForSequenceClassification.from_pretrained(
                    RERANKER_MODEL, local_files_only=True,
                )
                model.to(device).eval()
                logger.info("Reranker 模型从本地缓存加载完成 (device=%s)", device)
                _reranker_model = model
                _reranker_tokenizer = tokenizer
                return _reranker_model, _reranker_tokenizer
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
                    tokenizer = AutoTokenizer.from_pretrained(RERANKER_MODEL)
                    model = AutoModelForSequenceClassification.from_pretrained(RERANKER_MODEL)
                    model.to(device).eval()
                    logger.info("Reranker 模型从 %s 加载完成 (device=%s)", mirror, device)
                    _reranker_model = model
                    _reranker_tokenizer = tokenizer
                    return _reranker_model, _reranker_tokenizer
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

    model, tokenizer = _load_reranker()
    device = next(model.parameters()).device

    pairs = [[query, t] for t in texts]
    features = tokenizer(
        pairs,
        padding=True,
        truncation=True,
        max_length=MAX_LENGTH,
        return_tensors="pt",
    )
    features = {k: v.to(device) for k, v in features.items()}

    import torch
    with torch.inference_mode():
        logits = model(**features).logits.squeeze(-1)

    scores = logits.tolist()
    # Ensure list (single-item tensor -> float)
    if isinstance(scores, float):
        scores = [scores]

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
