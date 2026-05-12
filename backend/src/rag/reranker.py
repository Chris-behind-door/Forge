"""Cross-encoder Reranker 模块 — ONNX Runtime 推理

使用 onnxruntime 替代 transformers + torch 加载 bge-reranker-v2-m3，
大幅减小打包体积（不需要 torch，仅需 onnxruntime + transformers tokenizer）。
支持延迟加载和离线缓存。
"""

import logging
import threading
from pathlib import Path

import numpy as np


logger = logging.getLogger(__name__)

RERANKER_MODEL = "onnx-community/bge-reranker-v2-m3-ONNX"
_MAX_SEQ_LEN = 512

_lock = threading.Lock()
_session = None
_tokenizer = None
_load_error: Exception | None = None

# Model file to use (quantized = best balance of quality vs size)
_MODEL_FILE = "model_quantized.onnx"


def _resolve_model_dir() -> Path | None:
    """Locate the ONNX model directory from Modelscope cache or local path."""
    candidate_paths = [
        Path.home() / ".cache" / "modelscope" / "onnx-community" / "bge-reranker-v2-m3-ONNX",
        Path.home() / ".cache" / "huggingface" / "hub"
        / "models--onnx-community--bge-reranker-v2-m3-ONNX" / "snapshots",
    ]
    for base in candidate_paths:
        if base.is_dir():
            if base.name == "snapshots" and any(base.iterdir()):
                for snap in base.iterdir():
                    onnx_dir = snap / "onnx"
                    if (onnx_dir / _MODEL_FILE).exists():
                        return onnx_dir
            onnx_dir = base / "onnx"
            if (onnx_dir / _MODEL_FILE).exists():
                return onnx_dir
            if (base / _MODEL_FILE).exists():
                return base
    return None


def _load_reranker():
    """延迟加载 ONNX 模型和 tokenizer（线程安全）"""
    global _session, _tokenizer, _load_error

    if _session is not None:
        return _session, _tokenizer
    _load_error = None

    with _lock:
        if _session is not None:
            return _session, _tokenizer

        try:
            model_dir = _resolve_model_dir()
            if model_dir is None:
                raise FileNotFoundError(
                    "ONNX model not found. Download from:\n"
                    "  https://www.modelscope.cn/models/onnx-community/bge-reranker-v2-m3-ONNX/files"
                )

            onnx_path = model_dir / _MODEL_FILE
            if not onnx_path.exists():
                raise FileNotFoundError(f"ONNX model file not found: {onnx_path}")

            # Find tokenizer.json
            tokenizer_paths = [
                model_dir / "tokenizer.json",
                model_dir.parent / "tokenizer.json",
                model_dir.parent.parent / "tokenizer.json",
            ]
            tokenizer_path = next((p for p in tokenizer_paths if p.exists()), None)
            if not tokenizer_path:
                raise FileNotFoundError(f"tokenizer.json not found near {model_dir}")

            logger.info("加载 ONNX Reranker 模型: %s (size=%d MB)", onnx_path, onnx_path.stat().st_size >> 20)

            # Use HuggingFace tokenizers (Rust backend, no pytorch needed)
            from tokenizers import Tokenizer as HFTokenizer
            _tokenizer = HFTokenizer.from_file(str(tokenizer_path))

            import onnxruntime
            providers = ["CPUExecutionProvider"]
            _session = onnxruntime.InferenceSession(str(onnx_path), providers=providers)

            input_names = [i.name for i in _session.get_inputs()]
            logger.info("ONNX Reranker 加载完成 (inputs=%s)", input_names)
            return _session, _tokenizer

        except Exception as e:
            if e is not _load_error:
                _load_error = e
                logger.error("ONNX Reranker 加载失败: %s", e)
            raise


def _tokenize_with_tokenizers(tokenizer, query: str, texts: list[str], max_len: int):
    """Tokenize query-text pairs using HuggingFace tokenizers library."""
    tokenizer.enable_padding(pad_id=1, pad_type_id=0, length=max_len)
    tokenizer.enable_truncation(max_len)
    pairs = [[query, text] for text in texts]
    encoded = tokenizer.encode_batch(pairs, add_special_tokens=True, is_pretokenized=False)
    return {
        "input_ids": np.array([e.ids for e in encoded], dtype=np.int64),
        "attention_mask": np.array([e.attention_mask for e in encoded], dtype=np.int64),
        "token_type_ids": np.zeros((len(encoded), max_len), dtype=np.int64),
    }


def rerank(query: str, texts: list[str], top_k: int | None = None) -> list[float]:
    """
    对 query-doc 对计算相关性分数（ONNX Runtime 推理）

    Args:
        query: 查询文本
        texts: 文档文本列表
        top_k: 可选，只保留 top_k 个的分数（其余置 0）

    Returns:
        与 texts 等长的分数列表
    """
    if not texts:
        return []

    session, tokenizer = _load_reranker()
    input_names = [i.name for i in session.get_inputs()]

    onnx_inputs = _tokenize_with_tokenizers(tokenizer, query, texts, _MAX_SEQ_LEN)
    if "token_type_ids" not in input_names:
        onnx_inputs.pop("token_type_ids", None)

    logits = session.run(None, onnx_inputs)[0]

    if logits.shape[1] >= 2:
        scores = logits[:, 1].tolist()
    else:
        scores = logits[:, 0].tolist()

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
    """返回符合 scoring.py rank_candidates 签名的 reranker 函数

    签名: (query: str, texts: list[str]) -> list[float]
    """
    def _fn(query: str, texts: list[str]) -> list[float]:
        return rerank(query, texts, top_k=top_k)
    return _fn
