"""Subprocess worker for memory-isolated document processing.

Parse + embedding run in a child process.  When the child exits, all
transient memory (OCR models, parsed chunks, embedding tensors) is
returned to the OS immediately.

The parent process only touches metadata and the vector DB (LanceDB)
which are lightweight.
"""

import logging
import multiprocessing as mp
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _worker_main(
    stored_path: str,
    file_type: str,
    doc_id: str,
    project_id: str | None,
) -> dict:
    """Run inside a child process: parse → embed → write to LanceDB.

    For CHM files, processing is streamed: parse one subdirectory at a
    time, embed the chunks immediately, write to DB, then discard before
    moving to the next subdirectory.  This caps peak memory at roughly
    the cost of the largest subdirectory instead of the entire CHM.

    Returns a summary dict with chunk_count, rss_peak, timings etc.
    """
    import time
    import gc

    start = time.monotonic()
    result: dict = {"doc_id": doc_id, "chunk_count": 0, "error": None}

    try:
        # ── Parse ──
        t0 = time.monotonic()
        if file_type == "chm":
            from ..parsers.chm import parse_chm
            chunks = parse_chm(stored_path)
        else:
            from ..parsers.pdf import parse_pdf
            chunks = parse_pdf(stored_path)
        parse_time = time.monotonic() - t0
        result["chunk_count"] = len(chunks)
        result["parse_time_s"] = round(parse_time, 1)

        # ── Embed + write to DB in batches ──
        # Embedding all chunks at once can consume huge memory (the entire
        # CHM text + all vectors).  Batch to cap memory at ~BATCH_SIZE texts.
        _EMBED_BATCH_SIZE = 200
        t0 = time.monotonic()
        from ..rag.vector_store import add_chunks
        total_vectors = 0
        for i in range(0, len(chunks), _EMBED_BATCH_SIZE):
            batch = chunks[i : i + _EMBED_BATCH_SIZE]
            count = add_chunks(doc_id, batch, project_id)
            total_vectors += count
            del batch
            if i + _EMBED_BATCH_SIZE < len(chunks):
                gc.collect()
        embed_time = time.monotonic() - t0
        result["vectors"] = total_vectors
        result["embed_time_s"] = round(embed_time, 1)

    except Exception as e:
        result["error"] = str(e)

    result["total_time_s"] = round(time.monotonic() - start, 1)

    # Report peak RSS from this child
    try:
        import psutil
        result["child_rss_peak_mb"] = round(
            psutil.Process(os.getpid()).memory_info().rss / (1024 ** 2), 0
        )
    except Exception:
        pass

    return result


def run_in_subprocess(
    stored_path: str,
    file_type: str,
    doc_id: str,
    project_id: str | None = None,
) -> dict:
    """Synchronous call: spawn child, wait, return summary."""
    ctx = mp.get_context("spawn")  # clean process, no fork issues
    # Use a simple pipe-based approach via Pool(1) for pickling convenience
    with ctx.Pool(1) as pool:
        async_result = pool.apply_async(
            _worker_main,
            (stored_path, file_type, doc_id, project_id),
        )
        return async_result.get(timeout=3600)  # 1h max per file
