"""
向量存储模块（使用 LanceDB）

功能：
- 文档分块的向量化存储
- Hybrid 检索：LanceDB 原生向量 + FTS 全文搜索 + RRF 融合
- CrossEncoder 精排（可选）
- 按文档 ID 删除

检索策略（两阶段）：
1. 粗排：LanceDB hybrid search（向量语义 + FTS 全文搜索，RRF 融合）
2. 精排：CrossEncoder reranker 对 top 候选重排序

注意：重模块（lancedb, fastembed, torch）均为懒加载，不在模块顶部 import。
"""

import logging
import os
from typing import Any

from ..utils.paths import VECTOR_DIR

logger = logging.getLogger(__name__)

# 表名
CHUNKS_TABLE = "chunks"

# FTS 索引名称
FTS_INDEX_NAME = "text_idx"

# 懒加载的 ChunkRecord 模型（首次使用时构建）
_ChunkRecordModel = None


def _get_chunk_record():
    """Lazily build and cache the ChunkRecord LanceModel."""
    global _ChunkRecordModel
    if _ChunkRecordModel is not None:
        return _ChunkRecordModel

    from lancedb.pydantic import LanceModel, Vector
    from pydantic import Field
    from .embeddings import EMBEDDING_DIM

    class ChunkRecord(LanceModel):
        chunk_id: str = Field(description="分块唯一标识")
        doc_id: str = Field(description="所属文档 ID")
        text: str = Field(description="分块文本")
        page: int | None = Field(default=None, description="页码（PDF）")
        location: str | None = Field(default=None, description="位置标识（CHM等）")
        project_id: str | None = Field(default=None, description="所属项目，null 表示通用知识")
        vector: Vector(EMBEDDING_DIM) = Field(description="嵌入向量")

    _ChunkRecordModel = ChunkRecord
    return ChunkRecord


# Re-export ChunkRecord name for backward compatibility
# (other modules do `from ..rag.vector_store import ChunkRecord`)
ChunkRecord = property(lambda self: _get_chunk_record())


def get_db():
    """获取 LanceDB 连接"""
    import lancedb
    VECTOR_DIR.mkdir(parents=True, exist_ok=True)
    # Use forward slashes to avoid lance URL conversion issue on Windows
    # (drive letter gets stripped when converting backslash paths to file:// URLs)
    path = str(VECTOR_DIR).replace('\\', '/')
    return lancedb.connect(path)


def _get_or_create_table(db):
    """获取或创建表，必要时迁移 schema"""
    ChunkRecord = _get_chunk_record()
    if CHUNKS_TABLE in db.table_names():
        table = db.open_table(CHUNKS_TABLE)
        schema = table.schema
        pid_field = next((f for f in schema if f.name == "project_id"), None)
        needs_rebuild = pid_field is None or str(pid_field.type) != "utf8"
        if needs_rebuild:
            logger.info("Migrating schema v3: recreating table with project_id column")
            db.drop_table(CHUNKS_TABLE)
            return db.create_table(CHUNKS_TABLE, schema=ChunkRecord)
        return table
    return db.create_table(CHUNKS_TABLE, schema=ChunkRecord)


def _ensure_fts_index(table) -> None:
    """确保 FTS 全文搜索索引存在"""
    try:
        index_names = [idx.name for idx in table.list_indices()]
        if FTS_INDEX_NAME not in index_names:
            logger.info("Creating FTS index on 'text' column...")
            table.create_fts_index("text", replace=True)
            logger.info("FTS index created")
    except Exception as e:
        logger.warning("FTS index creation failed (hybrid search will be vector-only): %s", e)


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

    from .embeddings import embed_texts
    ChunkRecord = _get_chunk_record()

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

    # 重建 FTS 索引（增量索引在 LanceDB 社区版不可靠，重建更稳）
    _ensure_fts_index(table)

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

    safe_doc_id = doc_id.replace("'", "''")
    table.delete(f"doc_id = '{safe_doc_id}'")

    count_after = table.count_rows()

    # 删除后重建 FTS 索引
    if count_before != count_after:
        _ensure_fts_index(table)

    return count_before - count_after


def search_similar(
    query: str, top_k: int = 5, project_id: str | None = None
) -> list[dict[str, Any]]:
    """
    两阶段检索：LanceDB hybrid 粗排 → CrossEncoder 精排
    """
    from .embeddings import embed_query
    from .reranker import make_reranker_fn

    db = get_db()

    if CHUNKS_TABLE not in db.table_names():
        return []

    table = db.open_table(CHUNKS_TABLE)

    # 确保 FTS 索引存在
    has_fts = False
    try:
        index_names = [idx.name for idx in table.list_indices()]
        has_fts = FTS_INDEX_NAME in index_names
    except Exception:
        pass

    # 生成查询向量
    query_vector = embed_query(query)

    # 构建 project_id 过滤条件
    if project_id is not None:
        safe_pid = project_id.replace("'", "''")
        where_clause = f"project_id = '{safe_pid}' OR project_id IS NULL"
    else:
        where_clause = "project_id IS NULL"

    # 粗排候选数量
    n_candidates = top_k * 3

    # 第一阶段：粗排
    if has_fts:
        try:
            results = (
                table.search(
                    query_type="hybrid",
                    vector_column_name="vector",
                    fts_columns="text",
                )
                .vector(query_vector)
                .text(query)
                .where(where_clause)
                .limit(n_candidates)
                .to_list()
            )
        except Exception as e:
            logger.warning("Hybrid search failed, falling back to vector-only: %s", e)
            results = _vector_only_search(table, query_vector, where_clause, n_candidates)
    else:
        results = _vector_only_search(table, query_vector, where_clause, n_candidates)

    if not results:
        return []

    # 构建候选列表
    candidates = []
    for r in results:
        candidates.append(
            {
                "chunk_id": r.get("chunk_id", ""),
                "doc_id": r.get("doc_id", ""),
                "text": r.get("text", ""),
                "page": r.get("page"),
                "location": r.get("location"),
                "score": r.get("_relevance_score", 0),
            }
        )

    # 第二阶段：CrossEncoder 精排
    rerank_input = candidates[: top_k * 2]
    disable_reranker = os.environ.get("FORGE_DISABLE_RERANKER", "").strip().lower() in ("1", "true", "yes")
    if disable_reranker:
        logger.info("Reranker disabled by config, using hybrid scores")
        return candidates[:top_k]
    try:
        reranker_fn = make_reranker_fn(top_k=top_k)
        texts = [c["text"] for c in rerank_input]
        rerank_scores = reranker_fn(query, texts)
        for c, rs in zip(rerank_input, rerank_scores):
            c["reranker_score"] = rs
            c["score"] = rs
        rerank_input.sort(key=lambda x: x["score"], reverse=True)
        logger.info("Reranker applied to %d candidates", len(rerank_input))
        return rerank_input[:top_k]
    except Exception as e:
        logger.warning("Reranker unavailable, using hybrid scores: %s", e)
        return candidates[:top_k]


def _vector_only_search(table, query_vector: list[float], where_clause: str, limit: int) -> list[dict]:
    """纯向量搜索（FTS 不可用时的降级方案）"""
    return (
        table.search(query_vector, vector_column_name="vector")
        .where(where_clause)
        .limit(limit)
        .to_list()
    )


def get_adjacent_chunks(
    doc_id: str, chunk_indices: list[int], before: int = 1, after: int = 1
) -> list[dict[str, Any]]:
    """获取指定 chunk 前后的相邻分块（用于上下文扩展）"""
    ChunkRecord = _get_chunk_record()

    db = get_db()
    if CHUNKS_TABLE not in db.table_names():
        return []

    table = db.open_table(CHUNKS_TABLE)

    all_indices = set()
    for idx in chunk_indices:
        for offset in range(-before, after + 1):
            all_indices.add(idx + offset)

    chunk_ids = {f"{doc_id}_{i}" for i in sorted(all_indices)}

    results = []
    try:
        safe_doc_id = doc_id.replace("'", "''")
        rows = (
            table.search()
            .where(f"doc_id = '{safe_doc_id}'")
            .limit(50000)
            .to_pydantic(ChunkRecord)
        )
        for r in rows:
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

    seen = set()
    unique = []
    for r in sorted(results, key=lambda x: x["index"]):
        if r["chunk_id"] not in seen:
            seen.add(r["chunk_id"])
            unique.append(r)

    return unique


def get_chunk_count(doc_id: str | None = None) -> int:
    """获取分块数量"""
    db = get_db()

    if CHUNKS_TABLE not in db.table_names():
        return 0

    table = db.open_table(CHUNKS_TABLE)

    if doc_id:
        safe_doc_id = doc_id.replace("'", "''")
        results = table.search().where(f"doc_id = '{safe_doc_id}'").limit(10000).to_list()
        return len(results)

    return table.count_rows()
