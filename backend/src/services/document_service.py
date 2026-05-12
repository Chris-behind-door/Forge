"""Document upload, parsing, RAG processing, and lifecycle management."""

import asyncio
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel

from ..utils.paths import UPLOADS_DIR, METADATA_FILE, ensure_dirs

logger = logging.getLogger(__name__)


# ── Types ──


class Document(BaseModel):
    id: str
    name: str
    size: int
    file_hash: str
    file_type: str = "pdf"
    original_path: str
    stored_path: str
    uploaded_at: str
    chunk_count: int | None = None
    status: str = "pending"
    project_id: str | None = None


class DocumentListResponse(BaseModel):
    documents: list[Document]
    total: int


class DocumentUploadRequest(BaseModel):
    file_path: str
    project_id: str | None = None


class MoveDocumentRequest(BaseModel):
    project_id: str | None = None


class ChunkDetail(BaseModel):
    chunk_id: str
    doc_id: str
    text: str
    page: int | None = None
    location: str | None = None
    index: int
    doc_name: str
    file_type: str


# ── Metadata persistence ──


def _load_metadata() -> dict[str, Document]:
    if not METADATA_FILE.exists():
        return {}
    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {k: Document(**v) for k, v in data.items()}


def _save_metadata(documents: dict[str, Document]) -> None:
    ensure_dirs()
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump({k: v.model_dump() for k, v in documents.items()},
                  f, indent=2, ensure_ascii=False)


def _calculate_file_hash(file_path: Path, chunk_size: int = 8192) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()


# ── Processing tasks ──

# ── Memory-budgeted concurrent processing queue ──
#
# Phase 1: simple concurrency cap.  Phase 2 (after profiling with real
# data) will add psutil-based dynamic memory budgeting.

class _QueueItem(BaseModel):
    doc_id: str
    stored_path: str
    file_type: str = "pdf"

_MAX_CONCURRENT = 2  # hard cap on parallel processing tasks

_doc_queue: asyncio.Queue[_QueueItem] = asyncio.Queue()
_queue_worker_started = False
_running: set[str] = set()       # doc_ids currently being processed
_active_tasks: dict[str, asyncio.Task] = {}  # doc_id -> task ref for cancellation
_concurrency_sem: asyncio.Semaphore | None = None


def _delete_doc_chunks(doc_id: str) -> int:
    """Lazy wrapper for vector_store.delete_doc_chunks."""
    from ..rag.vector_store import delete_doc_chunks
    return delete_doc_chunks(doc_id)


async def process_document(doc_id: str, stored_path: str, file_type: str = "pdf") -> None:
    logger.info(f"[{doc_id[:8]}] 开始处理文档 (类型: {file_type})")

    metadata = _load_metadata()
    if doc_id not in metadata:
        logger.info(f"[{doc_id[:8]}] 文档不存在于元数据中，跳过")
        return
    doc = metadata[doc_id]

    try:
        import os as _os
        import psutil as _psutil
        _proc = _psutil.Process(_os.getpid())
        def _log_rss(label: str) -> None:
            rss = _proc.memory_info().rss / (1024 ** 2)
            logger.info(f"[{doc_id[:8]}] MEM [{label}] RSS={rss:.0f} MB")
    except ImportError:
        def _log_rss(label: str) -> None: pass

    try:
        doc.status = "processing"
        _save_metadata(metadata)
        file_size_mb = Path(stored_path).stat().st_size >> 20
        _log_rss(f"start ({file_type}, {file_size_mb} MB)")

        from .doc_worker import run_in_subprocess

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, run_in_subprocess, stored_path, file_type, doc_id, doc.project_id,
        )

        if result.get("error"):
            raise RuntimeError(result["error"])

        # Rebuild FTS index in parent process (subprocess may have created
        # a stale index that only covers its own data)
        try:
            from ..rag.vector_store import get_db, CHUNKS_TABLE, FTS_INDEX_NAME
            db = get_db()
            if CHUNKS_TABLE in db.table_names():
                table = db.open_table(CHUNKS_TABLE)
                index_names = [idx.name for idx in table.list_indices()]
                if FTS_INDEX_NAME in index_names:
                    table.create_fts_index("text", replace=True)
                    logger.info(f"[{doc_id[:8]}] FTS index rebuilt")
        except Exception as fts_err:
            logger.warning(f"[{doc_id[:8]}] FTS index rebuild failed: {fts_err}")

        child_peak = result.get("child_rss_peak_mb", "?")
        _log_rss(
            f"done (child peak={child_peak} MB, "
            f"parse={result.get('parse_time_s','?')}s, "
            f"embed={result.get('embed_time_s','?')}s, "
            f"total={result.get('total_time_s','?')}s, "
            f"{result.get('chunk_count',0)} chunks)"
        )

        metadata = _load_metadata()
        if doc_id in metadata:
            metadata[doc_id].chunk_count = result.get("vectors", result.get("chunk_count", 0))
            metadata[doc_id].status = "ready"
            _save_metadata(metadata)

    except asyncio.CancelledError:
        logger.info(f"[{doc_id[:8]}] 任务被取消，清理状态")
        metadata = _load_metadata()
        if doc_id in metadata:
            metadata[doc_id].status = "pending"
            _save_metadata(metadata)
        raise
    except Exception as e:
        logger.error(f"[{doc_id[:8]}] 处理失败: {e}")
        metadata = _load_metadata()
        if doc_id in metadata:
            metadata[doc_id].status = "error"
            _save_metadata(metadata)
        raise


def _get_sem() -> asyncio.Semaphore:
    global _concurrency_sem
    if _concurrency_sem is None:
        _concurrency_sem = asyncio.Semaphore(_MAX_CONCURRENT)
    return _concurrency_sem


def _ensure_worker() -> None:
    """Start the queue worker if not already running."""
    global _queue_worker_started
    if not _queue_worker_started:
        asyncio.create_task(_queue_worker())
        _queue_worker_started = True


async def _queue_worker() -> None:
    """Dispatch queue items up to the concurrency limit."""
    global _queue_worker_started
    try:
        while True:
            item = await _doc_queue.get()
            sem = _get_sem()
            await sem.acquire()
            _running.add(item.doc_id)
            logger.info(
                f"[{item.doc_id[:8]}] 开始处理 "
                f"(并发: {len(_running)}/{_MAX_CONCURRENT}, "
                f"队列剩余: {_doc_queue.qsize()})"
            )
            task = asyncio.create_task(
                _run_item(item), name=f"doc-proc-{item.doc_id[:8]}"
            )
            _active_tasks[item.doc_id] = task
            task.add_done_callback(lambda t, did=item.doc_id: _active_tasks.pop(did, None))
    except asyncio.CancelledError:
        _queue_worker_started = False


async def _run_item(item: _QueueItem) -> None:
    """Process one item and release the concurrency slot."""
    sem = _get_sem()
    try:
        await process_document(item.doc_id, item.stored_path, item.file_type)
    except Exception:
        logger.exception(f"[{item.doc_id[:8]}] 处理异常")
    finally:
        _running.discard(item.doc_id)
        sem.release()
        _doc_queue.task_done()


def start_processing(doc_id: str, stored_path: str, file_type: str = "pdf") -> None:
    """Enqueue a document for concurrent processing."""
    metadata = _load_metadata()
    if doc_id in metadata:
        metadata[doc_id].status = "queued"
        _save_metadata(metadata)
    _doc_queue.put_nowait(_QueueItem(
        doc_id=doc_id, stored_path=stored_path, file_type=file_type,
    ))
    logger.info(f"[{doc_id[:8]}] 已加入处理队列 (队列深度: {_doc_queue.qsize()})")
    _ensure_worker()


def cancel_processing(doc_id: str) -> bool:
    """Cancel a queued or actively processing document.

    - Removes from queue if not yet started.
    - Cancels the asyncio Task (which will terminate the subprocess).
    Returns True if anything was cancelled.
    """
    found = False

    # 1) Remove from queue
    temp: list[_QueueItem] = []
    while not _doc_queue.empty():
        try:
            item = _doc_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        if item.doc_id == doc_id:
            found = True
            logger.info(f"[{doc_id[:8]}] 已从队列移除")
            metadata = _load_metadata()
            if doc_id in metadata:
                metadata[doc_id].status = "pending"
                _save_metadata(metadata)
        else:
            temp.append(item)
    for item in temp:
        _doc_queue.put_nowait(item)

    # 2) Cancel running task
    task = _active_tasks.get(doc_id)
    if task and not task.done():
        task.cancel()
        found = True
        logger.info(f"[{doc_id[:8]}] 已取消处理任务")

    return found


def queue_status() -> dict:
    """Return current queue and concurrency status."""
    return {
        "queue_depth": _doc_queue.qsize(),
        "running": list(_running),
        "concurrency_limit": _MAX_CONCURRENT,
    }


async def resume_pending_documents() -> None:
    metadata = _load_metadata()
    for doc_id, doc in metadata.items():
        if doc.status in ("pending", "processing", "queued"):
            stored_path = Path(doc.stored_path)
            if stored_path.exists():
                logger.info(f"[{doc_id[:8]}] 恢复处理: {doc.name} (状态: {doc.status})")
                if doc.status in ("processing", "queued"):
                    metadata[doc_id].status = "pending"
                    _save_metadata(metadata)
                start_processing(doc_id, str(stored_path), doc.file_type)


# ── Upload / Delete / Reprocess ──


async def upload(request: DocumentUploadRequest) -> Document:
    import shutil

    source_path = Path(request.file_path)
    if not source_path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {request.file_path}")
    if not source_path.is_file():
        raise HTTPException(status_code=400, detail=f"不是有效文件: {request.file_path}")

    suffix = source_path.name.lower().split(".")[-1] if "." in source_path.name else ""
    if suffix not in ("pdf", "chm"):
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: .{suffix}，仅支持 PDF 和 CHM")

    file_hash = _calculate_file_hash(source_path)
    metadata = _load_metadata()
    for doc in metadata.values():
        if doc.file_hash == file_hash:
            # 如果旧文档处于 error 状态，自动清除后允许重新上传
            if doc.status == "error":
                logger.info(f"发现同哈希的 error 文档 {doc.id[:8]}，自动清除以允许重新上传")
                cancel_processing(doc.id)
                stored_path = Path(doc.stored_path)
                if stored_path.exists():
                    stored_path.unlink()
                _delete_doc_chunks(doc.id)
                del metadata[doc.id]
                _save_metadata(metadata)
                break
            raise HTTPException(status_code=409, detail=f"文件内容已存在: {doc.name}")

    doc_id = str(uuid4())
    stored_path = UPLOADS_DIR / f"{doc_id}.{suffix}"
    ensure_dirs()

    file_size = source_path.stat().st_size
    shutil.copy2(source_path, stored_path)
    logger.info(f"[{doc_id[:8]}] 文件已复制: {source_path.name}")

    document = Document(
        id=doc_id, name=source_path.name, size=file_size, file_hash=file_hash,
        file_type=suffix, original_path=str(source_path.absolute()),
        stored_path=str(stored_path), uploaded_at=datetime.now().isoformat(),
        status="pending", project_id=request.project_id,
    )
    metadata[doc_id] = document
    _save_metadata(metadata)
    start_processing(doc_id, str(stored_path), suffix)
    return document


def list_documents(
    project_id: str | None = None, filter_null: bool = False,
) -> DocumentListResponse:
    metadata = _load_metadata()
    if project_id is not None:
        docs = [d for d in metadata.values() if d.project_id == project_id]
    elif filter_null:
        docs = [d for d in metadata.values() if d.project_id is None]
    else:
        docs = list(metadata.values())
    return DocumentListResponse(documents=docs, total=len(docs))


async def delete(doc_id: str) -> dict:
    metadata = _load_metadata()
    if doc_id not in metadata:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
    doc = metadata[doc_id]

    cancelled = cancel_processing(doc_id)
    if cancelled:
        # Give subprocess a moment to release file handles
        await asyncio.sleep(0.5)

    stored_path = Path(doc.stored_path)
    if stored_path.exists():
        for attempt in range(5):
            try:
                stored_path.unlink()
                logger.info(f"[{doc_id[:8]}] 文件已删除")
                break
            except PermissionError:
                if attempt < 4:
                    await asyncio.sleep(0.5)
                else:
                    logger.warning(
                        f"[{doc_id[:8]}] 文件仍被占用，跳过删除: {stored_path}"
                    )

    _delete_doc_chunks(doc_id)
    logger.info(f"[{doc_id[:8]}] 向量数据已删除")

    del metadata[doc_id]
    _save_metadata(metadata)
    return {"status": "deleted", "id": doc_id}


async def reprocess(doc_id: str) -> dict:
    metadata = _load_metadata()
    if doc_id not in metadata:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
    doc = metadata[doc_id]
    stored_path = Path(doc.stored_path)
    if not stored_path.exists():
        raise HTTPException(status_code=404, detail=f"源文件不存在: {doc.stored_path}")

    cancel_processing(doc_id)
    deleted = _delete_doc_chunks(doc_id)
    logger.info(f"[{doc_id[:8]}] 删除旧向量数据: {deleted} 条")

    metadata[doc_id].status = "pending"
    metadata[doc_id].chunk_count = None
    _save_metadata(metadata)
    start_processing(doc_id, str(stored_path), doc.file_type)
    logger.info(f"[{doc_id[:8]}] 开始重新处理")
    return {"status": "reprocessing", "id": doc_id, "deleted_chunks": deleted}


async def reprocess_all() -> dict:
    metadata = _load_metadata()
    results = []
    for doc_id, doc in metadata.items():
        stored_path = Path(doc.stored_path)
        if not stored_path.exists():
            results.append({"id": doc_id, "status": "skipped", "reason": "文件不存在"})
            continue
        cancel_processing(doc_id)
        deleted = _delete_doc_chunks(doc_id)
        metadata[doc_id].status = "pending"
        metadata[doc_id].chunk_count = None
        start_processing(doc_id, str(stored_path), doc.file_type)
        results.append({
            "id": doc_id, "name": doc.name, "type": doc.file_type,
            "status": "reprocessing", "deleted_chunks": deleted,
        })
    _save_metadata(metadata)
    return {"status": "started", "total": len(results), "documents": results}


def get(doc_id: str) -> Document:
    metadata = _load_metadata()
    if doc_id not in metadata:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
    return metadata[doc_id]


async def move(doc_id: str, project_id: str | None) -> Document:
    metadata = _load_metadata()
    if doc_id not in metadata:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
    doc = metadata[doc_id]
    if doc.project_id == project_id:
        return doc

    metadata[doc_id].project_id = project_id
    _save_metadata(metadata)

    from ..rag.vector_store import get_db, CHUNKS_TABLE
    db = get_db()
    if CHUNKS_TABLE in db.table_names():
        table = db.open_table(CHUNKS_TABLE)
        safe_doc_id = doc_id.replace("'", "''")
        table.update(
            where=f"doc_id = '{safe_doc_id}'",
            values={"project_id": project_id},
        )
        logger.info(f"[{doc_id[:8]}] 已移动到 project_id={project_id}")
    return metadata[doc_id]


def get_chunk_detail(doc_id: str, chunk_index: int) -> ChunkDetail:
    from ..rag.vector_store import get_db, CHUNKS_TABLE, _get_chunk_record

    ChunkRecord = _get_chunk_record()

    metadata = _load_metadata()
    if doc_id not in metadata:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
    doc = metadata[doc_id]
    if doc.status != "ready":
        raise HTTPException(status_code=400, detail=f"文档尚未处理完成: {doc.status}")

    db = get_db()
    if CHUNKS_TABLE not in db.table_names():
        raise HTTPException(status_code=404, detail="向量数据不存在")

    table = db.open_table(CHUNKS_TABLE)
    target_chunk_id = f"{doc_id}_{chunk_index}"
    safe_chunk_id = target_chunk_id.replace("'", "''")
    rows = (
        table.search().where(f"chunk_id = '{safe_chunk_id}'")
        .limit(1).to_pydantic(ChunkRecord)
    )

    if rows:
        r = rows[0]
        return ChunkDetail(
            chunk_id=r.chunk_id, doc_id=r.doc_id, text=r.text,
            page=r.page, location=r.location, index=chunk_index,
            doc_name=doc.name, file_type=doc.file_type,
        )
    raise HTTPException(status_code=404, detail=f"Chunk 不存在: {target_chunk_id}")
