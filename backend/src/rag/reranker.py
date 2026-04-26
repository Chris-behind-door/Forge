"""
Cross-encoder Reranker 模块

使用 sentence-transformers CrossEncoder 加载 bge-reranker-v2-m3。
延迟加载：首次调用时才加载模型。

集成方式：
- scoring.py 的 rank_candidates() 已预留 reranker 接口
- vector_store.py 的 search_similar() 调用 rank_candidates 时传入 reranker
"""

import logging
import os
import threading

logger = logging.getLogger(__name__)

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"

_lock = threading.Lock()
_reranker_model = None
_load_error: Exception | None = None


def _load_reranker():
    """延迟加载 reranker 模型（线程安全）"""
    global _reranker_model, _load_error

    if _reranker_model is not None:
        return _reranker_model
    if _load_error is not None:
        raise _load_error

    with _lock:
        if _reranker_model is not None:
            return _reranker_model
        if _load_error is not None:
            raise _load_error

        try:
            from sentence_transformers import CrossEncoder

            logger.info("正在加载 Reranker 模型 %s ...", RERANKER_MODEL)
            model = CrossEncoder(RERANKER_MODEL, max_length=512)
            logger.info("Reranker 模型加载完成")
            _reranker_model = model
            return _reranker_model
        except Exception as e:
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
        与 texts 等长的分数列表（CrossEncoder 原始 logits，已按降序排序的索引）
    """
    if not texts:
        return []

    model = _load_reranker()

    # CrossEncoder.predict 接受 [[query, doc], ...] 格式
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
