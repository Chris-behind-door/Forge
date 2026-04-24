"""Document API routes — thin HTTP layer."""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ..services import document_service as ds
from ..services import chm_service as chm
from ..services.document_service import (
    DocumentUploadRequest,
    MoveDocumentRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=ds.Document)
async def upload_document(request: DocumentUploadRequest) -> ds.Document:
    return await ds.upload(request)


@router.get("", response_model=ds.DocumentListResponse)
async def list_documents(
    project_id: str | None = Query(default=None),
    filter_null: bool = Query(default=False),
) -> ds.DocumentListResponse:
    return ds.list_documents(project_id, filter_null)


@router.delete("/{doc_id}")
async def delete_document(doc_id: str) -> dict:
    return await ds.delete(doc_id)


@router.post("/{doc_id}/reprocess")
async def reprocess_document(doc_id: str) -> dict:
    return await ds.reprocess(doc_id)


@router.post("/reprocess-all")
async def reprocess_all_documents() -> dict:
    return await ds.reprocess_all()


@router.get("/{doc_id}", response_model=ds.Document)
async def get_document(doc_id: str) -> ds.Document:
    return ds.get(doc_id)


@router.put("/{doc_id}/move", response_model=ds.Document)
async def move_document(doc_id: str, req: MoveDocumentRequest) -> ds.Document:
    return await ds.move(doc_id, req.project_id)


@router.get("/{doc_id}/chunks/{chunk_index}", response_model=ds.ChunkDetail)
async def get_chunk_detail(doc_id: str, chunk_index: int) -> ds.ChunkDetail:
    if chunk_index < 0:
        raise HTTPException(status_code=400, detail="chunk_index 不能为负数")
    return ds.get_chunk_detail(doc_id, chunk_index)


@router.get("/{doc_id}/file")
async def get_document_file(doc_id: str):
    doc = ds.get(doc_id)
    file_path = Path(doc.stored_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在于磁盘")

    media_types = {"pdf": "application/pdf", "chm": "application/octet-stream"}
    return FileResponse(
        path=str(file_path),
        media_type=media_types.get(doc.file_type, "application/octet-stream"),
    )


@router.get("/{doc_id}/chm-html")
async def get_chm_html(doc_id: str, path: str = ""):
    return chm.get_chm_html(doc_id, path)


@router.get("/{doc_id}/{subpath:path}")
async def get_chm_static_fallback(doc_id: str, subpath: str):
    return chm.get_chm_static(doc_id, subpath)
