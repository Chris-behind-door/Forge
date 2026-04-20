"""
向量存储模块（使用 LanceDB）

功能：
- 文档分块的向量化存储
- 混合检索：向量语义 + 关键词匹配
- 按文档 ID 删除

检索策略：
- 向量检索：语义相似度
- 关键词检索：简单的包含匹配加分
- 融合两者分数，提高检索准确性
"""

import logging
import re
from typing import Any

import lancedb
from lancedb.pydantic import LanceModel, Vector
from pydantic import Field

import logging

logger = logging.getLogger(__name__)

from ..utils.paths import VECTOR_DIR
from .embeddings import EMBEDDING_DIM, embed_query, embed_texts

# 表名
CHUNKS_TABLE = "chunks"

# 混合检索权重
VECTOR_WEIGHT = 0.7  # 向量检索权重
KEYWORD_WEIGHT = 0.3  # 关键词检索权重


class ChunkRecord(LanceModel):
    """分块记录结构"""

    chunk_id: str = Field(description="分块唯一标识")
    doc_id: str = Field(description="所属文档 ID")
    text: str = Field(description="分块文本")
    page: int | None = Field(default=None, description="页码（PDF）")
    location: str | None = Field(default=None, description="位置标识（CHM等）")
    project_id: str | None = Field(default=None, description="所属项目，null 表示通用知识")
    vector: Vector(EMBEDDING_DIM) = Field(description="嵌入向量")


def get_db() -> lancedb.DBConnection:
    """获取 LanceDB 连接"""
    VECTOR_DIR.mkdir(parents=True, exist_ok=True)
    return lancedb.connect(str(VECTOR_DIR))


def _get_or_create_table(db: lancedb.DBConnection) -> lancedb.table.Table:
    """获取或创建表，必要时迁移 schema"""
    if CHUNKS_TABLE in db.table_names():
        table = db.open_table(CHUNKS_TABLE)
        schema = table.schema
        pid_field = next((f for f in schema if f.name == "project_id"), None)
        # Need rebuild if column missing, or type is not string (e.g. "null" type from bad migration)
        needs_rebuild = pid_field is None or str(pid_field.type) != "utf8"
        if needs_rebuild:
            logger.info("Migrating schema v3: recreating table with project_id column")
            # Cannot add nullable column reliably via add_columns,
            # so drop and recreate. Existing vectors need reprocessing anyway.
            db.drop_table(CHUNKS_TABLE)
            return db.create_table(CHUNKS_TABLE, schema=ChunkRecord)
        return table
    return db.create_table(CHUNKS_TABLE, schema=ChunkRecord)


def _compute_keyword_score(query: str, text: str) -> float:
    """
    计算关键词匹配分数（简单版）

    匹配规则：
    - 查询词中的每个字符如果在文本中出现，加分
    - 连续匹配额外加分

    Args:
        query: 查询字符串
        text: 文档文本

    Returns:
        0-1 之间的分数
    """
    # 预处理：移除标点和空白，转小写
    query_clean = re.sub(r"[^\w\u4e00-\u9fff]", "", query.lower())
    text_clean = re.sub(r"[^\w\u4e00-\u9fff]", "", text.lower())

    if not query_clean or not text_clean:
        return 0.0

    # 统计查询词中字符在文本中出现的比例
    matched_chars = sum(1 for c in query_clean if c in text_clean)
    char_ratio = matched_chars / len(query_clean)

    # 检查是否有连续子串匹配（加分）
    # 尝试 2-4 字符的子串
    bonus = 0.0
    for n in range(2, min(5, len(query_clean) + 1)):
        for i in range(len(query_clean) - n + 1):
            substring = query_clean[i : i + n]
            if substring in text_clean:
                bonus += 0.1 * n  # 越长的匹配加分越多

    # 最终分数：字符匹配 + 连续匹配奖励，限制在 0-1
    score = min(1.0, char_ratio * 0.5 + bonus)
    return score


def add_chunks(doc_id: str, chunks: list[dict], project_id: str | None = None) -> int:
    """
    添加文档分块到向量存储

    Args:
        doc_id: 文档 ID
        chunks: 分块列表，每个包含 'text', 'page', 'chunk_id'

    Returns:
        添加的分块数量
    """
    if not chunks:
        return 0

    db = get_db()
    table = _get_or_create_table(db)

    # 生成嵌入向量
    texts = [c["text"] for c in chunks]
    embeddings = embed_texts(texts)

    # 构建记录
    records = []
    for i, chunk in enumerate(chunks):
        record = ChunkRecord(
            chunk_id=f"{doc_id}_{chunk['chunk_id']}",
            doc_id=doc_id,
            text=chunk["text"],
            page=chunk.get("page"),
            location=chunk.get("location"),
            project_id=project_id,
            vector=embeddings[i],
        )
        records.append(record)

    # 添加到表
    table.add(records)

    return len(records)


def delete_doc_chunks(doc_id: str) -> int:
    """
    删除文档的所有分块

    Args:
        doc_id: 文档 ID

    Returns:
        删除的分块数量
    """
    db = get_db()

    if CHUNKS_TABLE not in db.table_names():
        return 0

    table = db.open_table(CHUNKS_TABLE)
    count_before = table.count_rows()

    # 删除（doc_id 是内部生成的 UUID，安全）
    table.delete(f"doc_id = '{doc_id}'")

    count_after = table.count_rows()
    return count_before - count_after


def search_similar(query: str, top_k: int = 5, project_id: str | None = None) -> list[dict[str, Any]]:
    """
    混合检索：向量语义 + 关键词匹配

    策略：
    1. 向量检索返回 top_k * 3 个候选
    2. 对候选计算关键词匹配分数
    3. 融合两种分数，返回 top_k 个结果

    Args:
        query: 查询字符串
        top_k: 返回结果数量

    Returns:
        匹配的分块列表，包含分数
    """
    db = get_db()

    if CHUNKS_TABLE not in db.table_names():
        return []

    table = db.open_table(CHUNKS_TABLE)

    # 向量检索：获取更多候选
    query_vector = embed_query(query)
    search_obj = table.search(query_vector).limit(top_k * 3)
    # 按 project_id 过滤：
    #   指定项目 → 该项目 + 通用知识
    #   不指定 → 只查通用知识
    if project_id is not None:
        safe_pid = project_id.replace("'", "''")
        search_obj = search_obj.where(f"project_id = '{safe_pid}' OR project_id IS NULL")
    else:
        search_obj = search_obj.where("project_id IS NULL")
    candidates = search_obj.to_pydantic(ChunkRecord)

    if not candidates:
        return []

    # 计算每个候选的混合分数
    scored_results = []
    for r in candidates:
        # 向量分数（距离越小越好，转换为 0-1 范围）
        vector_distance = getattr(r, "_distance", 1.0)
        vector_score = 1.0 / (1.0 + vector_distance)

        # 关键词匹配分数
        keyword_score = _compute_keyword_score(query, r.text)

        # 混合分数
        combined_score = VECTOR_WEIGHT * vector_score + KEYWORD_WEIGHT * keyword_score

        scored_results.append(
            {
                "chunk_id": r.chunk_id,
                "doc_id": r.doc_id,
                "text": r.text,
                "page": r.page,
                "location": r.location,
                "vector_score": vector_score,
                "keyword_score": keyword_score,
                "score": combined_score,
            }
        )

    # 按混合分数排序，返回 top_k
    scored_results.sort(key=lambda x: x["score"], reverse=True)

    return scored_results[:top_k]


def get_adjacent_chunks(
    doc_id: str, chunk_indices: list[int], before: int = 1, after: int = 1
) -> list[dict[str, Any]]:
    """
    获取指定 chunk 前后的相邻分块（用于上下文扩展）

    Args:
        doc_id: 文档 ID
        chunk_indices: 需要扩展的 chunk 序号列表
        before: 向前取几个 chunk
        after: 向后取几个 chunk

    Returns:
        去重后的相邻分块列表，按序号排序
    """
    db = get_db()
    if CHUNKS_TABLE not in db.table_names():
        return []

    table = db.open_table(CHUNKS_TABLE)

    # 计算需要获取的完整序号范围
    all_indices = set()
    for idx in chunk_indices:
        for offset in range(-before, after + 1):
            all_indices.add(idx + offset)

    # 转换为 chunk_id 列表
    chunk_ids = [f"{doc_id}_{i}" for i in sorted(all_indices)]

    # 查询该文档所有 chunk（LanceDB 无 IN 查询，暂用全量过滤）
    # TODO: 文档量大时优化为逐个查询或换存储方案
    results = []
    try:
        # 防御 SQL 注入：doc_id 应为 UUID，但做安全检查
        safe_doc_id = doc_id.replace("'", "''")
        rows = (
            table.search()
            .where(f"doc_id = '{safe_doc_id}'")
            .limit(50000)
            .to_pydantic(ChunkRecord)
        )
        # 按 chunk_id 过滤
        for r in rows:
            # chunk_id 格式: {doc_id}_{index}
            parts = r.chunk_id.rsplit("_", 1)
            if len(parts) == 2 and r.chunk_id in chunk_ids:
                idx = int(parts[1])
                results.append(
                    {
                        "chunk_id": r.chunk_id,
                        "doc_id": r.doc_id,
                        "text": r.text,
                        "page": r.page,
                        "location": r.location,
                        "index": idx,
                    }
                )
    except Exception:
        return []

    # 去重并按序号排序
    seen = set()
    unique = []
    for r in sorted(results, key=lambda x: x["index"]):
        if r["chunk_id"] not in seen:
            seen.add(r["chunk_id"])
            unique.append(r)

    return unique


def get_chunk_count(doc_id: str | None = None) -> int:
    """
    获取分块数量

    Args:
        doc_id: 可选的文档 ID 过滤

    Returns:
        分块数量
    """
    db = get_db()

    if CHUNKS_TABLE not in db.table_names():
        return 0

    table = db.open_table(CHUNKS_TABLE)

    if doc_id:
        results = table.search().where(f"doc_id = '{doc_id}'").limit(10000).to_list()
        return len(results)

    return table.count_rows()
