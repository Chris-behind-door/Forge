"""
Embedding module for RAG pipeline.
Uses fastembed with bge-small-zh for Chinese text.
"""

import os

# 强制离线模式（国内网络环境）
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

from fastembed import TextEmbedding

from ..utils.paths import VECTOR_DIR

# Model configuration
EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
EMBEDDING_DIM = 512  # bge-small-zh dimension

# Cache directory
CACHE_DIR = VECTOR_DIR / "cache"

# Lazy-loaded embedding model
_embedding_model: TextEmbedding | None = None


def get_embedding_model() -> TextEmbedding:
    """Get or create embedding model instance (offline mode)."""
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = TextEmbedding(
            EMBEDDING_MODEL,
            cache_dir=str(CACHE_DIR),
            local_files_only=True,
        )
    return _embedding_model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for a list of texts.

    Args:
        texts: List of text strings to embed

    Returns:
        List of embedding vectors
    """
    model = get_embedding_model()
    embeddings = list(model.embed(texts))
    return [e.tolist() for e in embeddings]


def embed_query(query: str) -> list[float]:
    """
    Generate embedding for a single query.

    Args:
        query: Query string

    Returns:
        Embedding vector
    """
    embeddings = embed_texts([query])
    return embeddings[0]
