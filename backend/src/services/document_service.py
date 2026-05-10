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

_processing_tasks: dict[str, asyncio.Task] = {}


def _delete_doc_chunks(doc_id: str) -> int:
    """Lazy wrapper for vector_store.delete_doc_chunks."""
    from ..rag.vector_store import delete_doc_chunks
    return delete_doc_chunks(doc_id)


async def process_document(doc_id: str, stored_path: str, file_type: str = "pdf") -> None:
    start_time = datetime.now()
    logger.info(f"[{doc_id[:8]}] 开始处理文档 (类型: {file_type})")

    metadata = _load_metadata()
    if doc_id not in metadata:
        logger.info(f"[{doc_id[:8]}] 文档不存在于元数据中，跳过")
        return
    doc = metadata[doc_id]

    try:
        doc.status = "processing"
        _save_metadata(metadata)
        logger.info(f"[{doc_id[:8]}] 状态更新: processing")

        from ..parsers.chm import parse_chm
        from ..parsers.pdf import parse_pdf
        from ..rag.vector_store import add_chunks

        step_start = datetime.now()
        parser_func = parse_chm if file_type == "chm" else parse_pdf
        loop = asyncio.get_event_loop()
        chunks = await loop.run_in_executor(None, parser_func, stored_path)
        elapsed = (datetime.now() - step_start).total_seconds()
        logger.info(f"[{doc_id[:8]}] 解析完成: {len(chunks)} 个分块, 耗时 {elapsed:.2f}s")

        step_start = datetime.now()
        logger.info(f"[{doc_id[:8]}] 开始向量化...")
        chunk_count = await loop.run_in_executor(
            None, add_chunks, doc_id, chunks, doc.project_id,
        )
        elapsed = (datetime.now() - step_start).total_seconds()
        logger.info(f"[{doc_id[:8]}] 向量化完成: {chunk_count} 个向量, 耗时 {elapsed:.2f}s")

        metadata = _load_metadata()
        if doc_id in metadata:
            metadata[doc_id].chunk_count = chunk_count
            metadata[doc_id].status = "ready"
            _save_metadata(metadata)

        total_elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"[{doc_id[:8]}] 处理完成, 总耗时 {total_elapsed:.2f}s")

    except asyncio.CancelledError:
        logger.info(f"[{doc_id[:8]}] 任务被取消，清理状态")
        metadata = _load_metadata()
        if doc_id in metadata:
            metadata[doc_id].status = "pending"
            _save_metadata(metadata)
        raise
    except Exception as e:
        logger.info(f"[{doc_id[:8]}] 处理失败: {e}")
        metadata = _load_metadata()
        if doc_id in metadata:
            metadata[doc_id].status = "error"
            _save_metadata(metadata)
        raise


def start_processing(doc_id: str, stored_path: str, file_type: str = "pdf") -> None:
    if doc_id in _processing_tasks:
        existing = _processing_tasks[doc_id]
        if not existing.done():
            existing.cancel()
    task = asyncio.create_task(process_document(doc_id, stored_path, file_type))
    _processing_tasks[doc_id] = task


def cancel_processing(doc_id: str) -> bool:
    if doc_id in _processing_tasks:
        task = _processing_tasks[doc_id]
        if not task.done():
            task.cancel()
            logger.info(f"[{doc_id[:8]}] 已发送取消信号")
            return True
    return False


async def resume_pending_documents() -> None:
    metadata = _load_metadata()
    for doc_id, doc in metadata.items():
        if doc.status in ("pending", "processing"):
            stored_path = Path(doc.stored_path)
            if stored_path.exists():
                logger.info(f"[{doc_id[:8]}] 恢复处理: {doc.name} (状态: {doc.status})")
                if doc.status == "processing":
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
    cancel_processing(doc_id)

    stored_path = Path(doc.stored_path)
    if stored_path.exists():
        stored_path.unlink()
        logger.info(f"[{doc_id[:8]}] 文件已删除")

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
