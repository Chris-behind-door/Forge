"""
通用评分与排序层

提供统一的检索结果评分和排序逻辑，支持：
- 向量相似度 + 关键词匹配的混合评分
- 可选 reranker（未来扩展）

使用方：
- RAG 知识库检索（LanceDB）
- 决议关联匹配（Kùzu）
"""

import logging
import re
from typing import Any, Callable, Sequence

logger = logging.getLogger(__name__)


def compute_keyword_score(query: str, text: str) -> float:
    """
    计算关键词匹配分数

    规则：
    - 查询词中每个字符在文本中出现则加分
    - 连续子串匹配额外加分
    - 返回 0~1 分数
    """
    query_clean = re.sub(r"[^\w\u4e00-\u9fff]", "", query.lower())
    text_clean = re.sub(r"[^\w\u4e00-\u9fff]", "", text.lower())

    if not query_clean or not text_clean:
        return 0.0

    matched_chars = sum(1 for c in query_clean if c in text_clean)
    char_ratio = matched_chars / len(query_clean)

    # 连续子串匹配奖励（2~4 字符）
    bonus = 0.0
    for n in range(2, min(5, len(query_clean) + 1)):
        for i in range(len(query_clean) - n + 1):
            substring = query_clean[i : i + n]
            if substring in text_clean:
                bonus += 0.1 * n

    return min(1.0, char_ratio * 0.5 + bonus)


def compute_hybrid_score(
    vector_score: float,
    keyword_score: float,
    vector_weight: float = 0.7,
    keyword_weight: float = 0.3,
) -> float:
    """加权混合评分"""
    return vector_weight * vector_score + keyword_weight * keyword_score


def cosine_to_score(cosine: float) -> float:
    """
    将 cosine similarity（-1~1）转换为 0~1 的分数。
    对于正常检索场景（cosine >= 0），直接返回。
    """
    return max(0.0, cosine)


def rank_candidates(
    candidates: Sequence[dict[str, Any]],
    query: str,
    *,
    vector_weight: float = 0.7,
    keyword_weight: float = 0.3,
    score_key: str = "vector_score",
    text_key: str = "text",
    reranker: Callable[[str, list[str]], list[float]] | None = None,
) -> list[dict[str, Any]]:
    """
    通用排序：混合评分 + 可选 reranker

    Args:
        candidates: 候选列表，每个 dict 需包含 score_key 和 text_key
        query: 查询文本
        vector_weight: 向量分数权重
        keyword_weight: 关键词分数权重
        score_key: 向量分数在 dict 中的 key
        text_key: 文本在 dict 中的 key
        reranker: 可选的 reranker 函数，签名 (query, texts) -> scores

    Returns:
        排序后的候选列表（原地修改并排序）
    """
    if not candidates:
        return []

    results = []

    # Step 1: 混合评分
    for c in candidates:
        vs = c.get(score_key, 0.0)
        # 如果向量分数是 cosine similarity，先转换
        if -1 <= vs <= 1:
            vs = cosine_to_score(vs)
        ks = compute_keyword_score(query, c.get(text_key, ""))
        hybrid = compute_hybrid_score(vs, ks, vector_weight, keyword_weight)

        entry = dict(c)
        entry["vector_score_raw"] = c.get(score_key)
        entry["keyword_score"] = ks
        entry["score"] = hybrid
        results.append(entry)

    # Step 2: 可选 reranker
    if reranker is not None:
        texts = [r.get(text_key, "") for r in results]
        try:
            rerank_scores = reranker(query, texts)
            for r, rs in zip(results, rerank_scores):
                # reranker 分数替换最终分数
                r["reranker_score"] = rs
                r["score"] = rs
            logger.info("Reranker applied to %d candidates", len(results))
        except Exception as e:
            logger.warning("Reranker failed, using hybrid scores: %s", e)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results
