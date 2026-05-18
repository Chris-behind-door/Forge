"""Subprocess worker for memory-isolated document processing.

Parse + embedding run in a child process.  When the child exits, all
transient memory (OCR models, parsed chunks, embedding tensors) is
returned to the OS immediately.

The parent process only touches metadata and the vector DB (LanceDB)
which are lightweight.

Pipeline mode: parsers yield batches of chunks, each batch is embedded
and written to DB immediately, then discarded before the next batch.
This caps peak memory at one batch + the embedding model (~2GB).
"""

import logging
import multiprocessing as mp
import os

logger = logging.getLogger(__name__)


def _get_existing_chunk_ids(doc_id: str) -> set[str]:
    """Query LanceDB for chunk_ids already stored for this doc."""
    try:
        from ..rag.vector_store import get_db, CHUNKS_TABLE, _get_chunk_record
        ChunkRecord = _get_chunk_record()
        db = get_db()
        if CHUNKS_TABLE not in db.table_names():
            return set()
        table = db.open_table(CHUNKS_TABLE)
        safe_doc_id = doc_id.replace("'", "''")
        rows = (
            table.search()
            .where(f"doc_id = '{safe_doc_id}'")
            .select(["chunk_id"])
            .limit(100000)
            .to_list()
        )
        return {r["chunk_id"] for r in rows}
    except Exception:
        return set()


def _worker_main(
    stored_path: str,
    file_type: str,
    doc_id: str,
    project_id: str | None,
) -> dict:
    """Run inside a child process: parse → embed → write to LanceDB.

    Uses the streaming parser variants (parse_*_iter) so that chunks
    are processed in batches, keeping peak memory bounded.

    Supports resume: if the doc was previously partially processed
    (e.g. timed out), existing chunks are skipped.

    Returns a summary dict with chunk_count, rss_peak, timings etc.
    """
    import gc
    import time

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [subproc] %(levelname)s %(message)s",
    )

    start = time.monotonic()
    result: dict = {"doc_id": doc_id, "chunk_count": 0, "error": None}

    try:
        from ..rag.vector_store import add_chunks

        existing_ids = _get_existing_chunk_ids(doc_id)
        if existing_ids:
            logger.info(
                "[subproc] Resuming %s: %d chunks already in DB, will skip",
                doc_id[:8], len(existing_ids),
            )

        if file_type == "chm":
            from ..parsers.chm import parse_chm_iter
            parser_iter = parse_chm_iter(stored_path)
        elif file_type == "docx":
            from ..parsers.docx import parse_docx_iter
            parser_iter = parse_docx_iter(stored_path)
        else:
            from ..parsers.pdf import parse_pdf_iter
            parser_iter = parse_pdf_iter(stored_path)

        total_vectors = 0
        total_chunks = 0
        total_skipped = 0
        t_embed = 0.0

        for batch in parser_iter:
            if existing_ids:
                filtered = [
                    c for c in batch
                    if f"{doc_id}_{c['chunk_id']}" not in existing_ids
                ]
                total_skipped += len(batch) - len(filtered)
                if not filtered:
                    continue
                batch = filtered

            total_chunks += len(batch)

            t0 = time.monotonic()
            count = add_chunks(doc_id, batch, project_id)
            t_embed += time.monotonic() - t0
            total_vectors += count

            del batch
            gc.collect()

        result["chunk_count"] = total_chunks
        result["vectors"] = total_vectors
        result["skipped"] = total_skipped
        result["embed_time_s"] = round(t_embed, 1)

    except Exception as e:
        import traceback
        result["error"] = str(e)
        result["error_tb"] = traceback.format_exc()

    result["total_time_s"] = round(time.monotonic() - start, 1)

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
    with ctx.Pool(1) as pool:
        async_result = pool.apply_async(
            _worker_main,
            (stored_path, file_type, doc_id, project_id),
        )
        return async_result.get(timeout=10800)  # 3h max per file
