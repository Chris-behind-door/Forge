"""
文档管理路由

功能：
- 文档上传、列表、删除
- 后台异步处理（OCR + 分块 + 向量化）
- 支持中断处理任务
- 启动时恢复未完成的处理

设计要点：
- 使用 asyncio 任务管理，支持取消
- 带时间戳的日志，便于性能分析
- 进程中断后可恢复处理
"""

import asyncio
import hashlib
import json
import logging
import mimetypes
import re
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..parsers.chm import parse_chm
from ..parsers.pdf import parse_pdf
from ..rag.vector_store import add_chunks, delete_doc_chunks
from ..utils.paths import UPLOADS_DIR, METADATA_FILE, ensure_dirs

router = APIRouter(prefix="/documents", tags=["documents"])

# 配置日志
logger = logging.getLogger(__name__)


# ============ 类型定义 ============


class DocumentUploadRequest(BaseModel):
    """文件上传请求（本地文件路径）"""

    file_path: str
    project_id: str | None = None  # 所属项目，null 表示通用知识


class Document(BaseModel):
    """文档元数据"""

    id: str
    name: str
    size: int
    file_hash: str  # SHA256 哈希，用于去重
    file_type: str = "pdf"  # pdf, chm
    original_path: str
    stored_path: str
    uploaded_at: str
    chunk_count: int | None = None
    status: str = "pending"  # pending, processing, ready, error
    project_id: str | None = None  # 所属项目，null 表示通用知识


class DocumentListResponse(BaseModel):
    """文档列表响应"""

    documents: list[Document]
    total: int


# ============ 任务管理 ============

# 运行中的处理任务 {doc_id: asyncio.Task}
_processing_tasks: dict[str, asyncio.Task] = {}


def _log(msg: str) -> None:
    """打印带时间戳的日志"""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    logger.info(f"[{timestamp}] {msg}")


# ============ 元数据管理 ============


def _load_metadata() -> dict[str, Document]:
    """从 JSON 文件加载文档元数据"""
    if not METADATA_FILE.exists():
        return {}

    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        return {k: Document(**v) for k, v in data.items()}


def _save_metadata(documents: dict[str, Document]) -> None:
    """保存文档元数据到 JSON 文件"""
    ensure_dirs()
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {k: v.model_dump() for k, v in documents.items()},
            f,
            indent=2,
            ensure_ascii=False,
        )


def _calculate_file_hash(file_path: Path, chunk_size: int = 8192) -> str:
    """计算文件的 SHA256 哈希"""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()


# ============ 文档处理 ============


async def process_document(
    doc_id: str, stored_path: str, file_type: str = "pdf"
) -> None:
    """
    后台任务：处理文档（解析 + 分块 + 向量化）

    Args:
        doc_id: 文档 ID
        stored_path: 文件存储路径
        file_type: 文件类型 (pdf, chm)
    """
    start_time = datetime.now()
    _log(f"[{doc_id[:8]}] 开始处理文档 (类型: {file_type})")

    metadata = _load_metadata()

    if doc_id not in metadata:
        _log(f"[{doc_id[:8]}] 文档不存在于元数据中，跳过")
        return

    doc = metadata[doc_id]

    try:
        # 更新状态为处理中
        doc.status = "processing"
        _save_metadata(metadata)
        _log(f"[{doc_id[:8]}] 状态更新: processing")

        # 步骤 1: 解析文档（根据类型选择解析器）
        step_start = datetime.now()

        # 选择解析器
        if file_type == "chm":
            _log(f"[{doc_id[:8]}] 开始 CHM 解析...")
            parser_func = parse_chm
        else:
            _log(f"[{doc_id[:8]}] 开始 PDF 解析...")
            parser_func = parse_pdf

        # 在线程池中运行同步的解析函数
        loop = asyncio.get_event_loop()
        chunks = await loop.run_in_executor(None, parser_func, stored_path)

        elapsed = (datetime.now() - step_start).total_seconds()
        _log(f"[{doc_id[:8]}] 解析完成: {len(chunks)} 个分块, 耗时 {elapsed:.2f}s")

        # 步骤 2: 向量化存储
        step_start = datetime.now()
        _log(f"[{doc_id[:8]}] 开始向量化...")

        chunk_count = await loop.run_in_executor(None, add_chunks, doc_id, chunks, doc.project_id)

        elapsed = (datetime.now() - step_start).total_seconds()
        _log(f"[{doc_id[:8]}] 向量化完成: {chunk_count} 个向量, 耗时 {elapsed:.2f}s")

        # 更新元数据
        metadata = _load_metadata()  # 重新加载（可能有并发更新）
        if doc_id in metadata:
            metadata[doc_id].chunk_count = chunk_count
            metadata[doc_id].status = "ready"
            _save_metadata(metadata)

        total_elapsed = (datetime.now() - start_time).total_seconds()
        _log(f"[{doc_id[:8]}] 处理完成, 总耗时 {total_elapsed:.2f}s")

    except asyncio.CancelledError:
        _log(f"[{doc_id[:8]}] 任务被取消，清理状态")
        metadata = _load_metadata()
        if doc_id in metadata:
            metadata[doc_id].status = "pending"  # 重置为待处理，方便恢复
            _save_metadata(metadata)
        raise

    except Exception as e:
        _log(f"[{doc_id[:8]}] 处理失败: {e}")
        metadata = _load_metadata()
        if doc_id in metadata:
            metadata[doc_id].status = "error"
            _save_metadata(metadata)
        raise


def _start_processing(doc_id: str, stored_path: str, file_type: str = "pdf") -> None:
    """启动后台处理任务"""
    # 如果已有任务在运行，先取消
    if doc_id in _processing_tasks:
        existing_task = _processing_tasks[doc_id]
        if not existing_task.done():
            existing_task.cancel()

    # 创建新任务
    task = asyncio.create_task(process_document(doc_id, stored_path, file_type))
    _processing_tasks[doc_id] = task


def _cancel_processing(doc_id: str) -> bool:
    """取消处理任务"""
    if doc_id in _processing_tasks:
        task = _processing_tasks[doc_id]
        if not task.done():
            task.cancel()
            _log(f"[{doc_id[:8]}] 已发送取消信号")
            return True
    return False


async def resume_pending_documents() -> None:
    """
    恢复未完成的文档处理

    启动时调用，检查是否有 processing 或 pending 状态的文档需要处理
    """
    metadata = _load_metadata()

    for doc_id, doc in metadata.items():
        if doc.status in ("pending", "processing"):
            stored_path = Path(doc.stored_path)
            if stored_path.exists():
                _log(f"[{doc_id[:8]}] 恢复处理: {doc.name} (状态: {doc.status})")
                # 重置为 pending，防止 processing 卡住
                if doc.status == "processing":
                    metadata[doc_id].status = "pending"
                    _save_metadata(metadata)
                _start_processing(doc_id, str(stored_path), doc.file_type)


# ============ API 端点 ============


@router.post("/upload", response_model=Document)
async def upload_document(request: DocumentUploadRequest) -> Document:
    """
    通过本地文件路径上传文档

    处理流程：
    1. 复制文件到 data/uploads 目录
    2. 在后台处理（解析 + 分块 + 向量化）

    支持格式：PDF, CHM
    """
    source_path = Path(request.file_path)

    # 验证源文件
    if not source_path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {request.file_path}")

    if not source_path.is_file():
        raise HTTPException(
            status_code=400, detail=f"不是有效文件: {request.file_path}"
        )

    # 检查文件类型
    suffix = source_path.name.lower().split(".")[-1] if "." in source_path.name else ""
    if suffix not in ("pdf", "chm"):
        raise HTTPException(
            status_code=400, detail=f"不支持的文件类型: .{suffix}，仅支持 PDF 和 CHM"
        )

    file_type = suffix

    # 计算哈希去重
    file_hash = _calculate_file_hash(source_path)

    metadata = _load_metadata()
    for doc in metadata.values():
        if doc.file_hash == file_hash:
            raise HTTPException(status_code=409, detail=f"文件内容已存在: {doc.name}")

    # 生成文档 ID 和存储路径
    doc_id = str(uuid4())
    stored_path = UPLOADS_DIR / f"{doc_id}.{file_type}"

    ensure_dirs()

    # 复制文件
    file_size = source_path.stat().st_size
    shutil.copy2(source_path, stored_path)
    _log(f"[{doc_id[:8]}] 文件已复制: {source_path.name}")

    # 创建文档记录
    document = Document(
        id=doc_id,
        name=source_path.name,
        size=file_size,
        file_hash=file_hash,
        file_type=file_type,
        original_path=str(source_path.absolute()),
        stored_path=str(stored_path),
        uploaded_at=datetime.now().isoformat(),
        status="pending",
        project_id=request.project_id,
    )

    metadata[doc_id] = document
    _save_metadata(metadata)

    # 启动后台处理
    _start_processing(doc_id, str(stored_path), file_type)

    return document


@router.get("", response_model=DocumentListResponse)
async def list_documents(project_id: str | None = Query(default=None)) -> DocumentListResponse:
    """列出已上传的文档，可按 project_id 筛选"""
    metadata = _load_metadata()
    if project_id is not None:
        documents = [d for d in metadata.values() if d.project_id == project_id]
    else:
        documents = list(metadata.values())
    return DocumentListResponse(documents=documents, total=len(documents))


@router.delete("/{doc_id}")
async def delete_document(doc_id: str) -> dict:
    """
    删除文档

    同时会：
    - 取消正在进行的处理任务
    - 删除向量存储中的数据
    """
    metadata = _load_metadata()

    if doc_id not in metadata:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")

    doc = metadata[doc_id]

    # 取消处理任务（如果有）
    _cancel_processing(doc_id)

    # 删除存储的文件
    stored_path = Path(doc.stored_path)
    if stored_path.exists():
        stored_path.unlink()
        _log(f"[{doc_id[:8]}] 文件已删除")

    # 删除向量存储
    delete_doc_chunks(doc_id)
    _log(f"[{doc_id[:8]}] 向量数据已删除")

    # 从元数据中移除
    del metadata[doc_id]
    _save_metadata(metadata)

    return {"status": "deleted", "id": doc_id}


@router.post("/{doc_id}/reprocess")
async def reprocess_document(doc_id: str) -> dict:
    """
    重新处理文档

    用于修复向量数据丢失或编码问题：
    - 删除旧的向量数据
    - 重新解析和向量化
    """
    metadata = _load_metadata()

    if doc_id not in metadata:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")

    doc = metadata[doc_id]

    # 检查文件是否存在
    stored_path = Path(doc.stored_path)
    if not stored_path.exists():
        raise HTTPException(status_code=404, detail=f"源文件不存在: {doc.stored_path}")

    # 取消现有处理任务
    _cancel_processing(doc_id)

    # 删除旧向量数据
    deleted = delete_doc_chunks(doc_id)
    _log(f"[{doc_id[:8]}] 删除旧向量数据: {deleted} 条")

    # 重置状态
    metadata[doc_id].status = "pending"
    metadata[doc_id].chunk_count = None
    _save_metadata(metadata)

    # 启动重新处理
    _start_processing(doc_id, str(stored_path), doc.file_type)
    _log(f"[{doc_id[:8]}] 开始重新处理")

    return {"status": "reprocessing", "id": doc_id, "deleted_chunks": deleted}


@router.post("/reprocess-all")
async def reprocess_all_documents() -> dict:
    """
    重新处理所有文档

    用于批量修复编码问题或 schema 变更后的数据迁移。
    会删除所有向量数据并重新处理。
    """
    metadata = _load_metadata()

    results = []
    for doc_id, doc in metadata.items():
        stored_path = Path(doc.stored_path)
        if not stored_path.exists():
            results.append({"id": doc_id, "status": "skipped", "reason": "文件不存在"})
            continue

        # 取消现有任务
        _cancel_processing(doc_id)

        # 删除旧向量数据
        deleted = delete_doc_chunks(doc_id)

        # 重置状态
        metadata[doc_id].status = "pending"
        metadata[doc_id].chunk_count = None

        # 启动重新处理
        _start_processing(doc_id, str(stored_path), doc.file_type)

        results.append(
            {
                "id": doc_id,
                "name": doc.name,
                "type": doc.file_type,
                "status": "reprocessing",
                "deleted_chunks": deleted,
            }
        )

    _save_metadata(metadata)

    return {"status": "started", "total": len(results), "documents": results}


@router.get("/{doc_id}", response_model=Document)
async def get_document(doc_id: str) -> Document:
    """获取单个文档信息"""
    metadata = _load_metadata()

    if doc_id not in metadata:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")

    return metadata[doc_id]


class ChunkDetail(BaseModel):
    """单个分块详情"""

    chunk_id: str
    doc_id: str
    text: str
    page: int | None = None
    location: str | None = None
    index: int
    doc_name: str
    file_type: str


@router.get("/{doc_id}/chunks/{chunk_index}", response_model=ChunkDetail)
async def get_chunk_detail(doc_id: str, chunk_index: int) -> ChunkDetail:
    """
    获取指定 chunk 的详情（用于引用跳转）
    """
    if chunk_index < 0:
        raise HTTPException(status_code=400, detail="chunk_index 不能为负数")
    from ..rag.vector_store import get_db, CHUNKS_TABLE, ChunkRecord

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

    # 查找目标 chunk
    safe_doc_id = doc_id.replace("'", "''")
    rows = (
        table.search()
        .where(f"doc_id = '{safe_doc_id}'")
        .limit(50000)
        .to_pydantic(ChunkRecord)
    )

    for r in rows:
        if r.chunk_id == target_chunk_id:
            return ChunkDetail(
                chunk_id=r.chunk_id,
                doc_id=r.doc_id,
                text=r.text,
                page=r.page,
                location=r.location,
                index=chunk_index,
                doc_name=doc.name,
                file_type=doc.file_type,
            )

    raise HTTPException(status_code=404, detail=f"Chunk 不存在: {target_chunk_id}")


@router.get("/{doc_id}/file")
async def get_document_file(doc_id: str):
    """
    获取文档文件（用于前端打开/下载）
    返回文件流，Content-Type 根据文件类型自动设置
    """
    metadata = _load_metadata()
    if doc_id not in metadata:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")

    doc = metadata[doc_id]
    file_path = Path(doc.stored_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在于磁盘")

    from fastapi.responses import FileResponse

    media_types = {"pdf": "application/pdf", "chm": "application/octet-stream"}
    media_type = media_types.get(doc.file_type, "application/octet-stream")

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
    )


@router.get("/{doc_id}/chm-html")
async def get_chm_html(doc_id: str, path: str = ""):
    """
    获取 CHM 文档中指定 HTML 文件的内容

    Args:
        doc_id: 文档 ID
        path: HTML 文件相对路径（来自 chunk 的 location 字段）
    """
    metadata = _load_metadata()
    if doc_id not in metadata:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")

    doc = metadata[doc_id]
    if doc.file_type != "chm":
        raise HTTPException(status_code=400, detail="仅支持 CHM 文档")

    if not path:
        raise HTTPException(status_code=400, detail="需要指定 path 参数")

    # CHM 解压目录: stored_path 同级的 {filename}_extracted/
    stored = Path(doc.stored_path)
    extract_dir = stored.parent / f"{stored.stem}_extracted"

    if not extract_dir.exists():
        raise HTTPException(
            status_code=404,
            detail="CHM 解压目录不存在，请重新导入文档以生成",
        )

    # 安全检查：防止路径遍历
    # 去掉查询参数（如 style.css?v=1 → style.css）
    clean_path = path.split("?")[0]
    file_path = (extract_dir / clean_path).resolve()
    if not str(file_path).startswith(str(extract_dir.resolve())):
        raise HTTPException(status_code=403, detail="非法路径")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {clean_path}")

    if file_path.suffix.lower() in (".html", ".htm"):
        # HTML 文件：检测编码，重写 URL 后返回
        raw = file_path.read_bytes()
        from ..parsers.chm import _detect_encoding

        encoding = _detect_encoding(raw)
        content = raw.decode(encoding, errors="replace")
        # 重写相对 URL 为绝对路径
        html_dir = str(Path(clean_path).parent) if "/" in clean_path else ""
        content = _rewrite_html_urls(content, doc_id, html_dir)
        from fastapi.responses import HTMLResponse

        return HTMLResponse(content=content)
    else:
        # 静态资源（图片、CSS、JS 等）
        from fastapi.responses import FileResponse

        mime_type, _ = mimetypes.guess_type(str(file_path))
        return FileResponse(
            path=str(file_path), media_type=mime_type or "application/octet-stream"
        )


def _rewrite_html_urls(html_content: str, doc_id: str, html_dir: str) -> str:
    """
    重写 CHM HTML 中的相对 URL，使其指向后端静态资源端点。

    例如 images/style.css → /documents/{doc_id}/chm-html?path={html_dir}/images/style.css
    """
    base = f"/documents/{doc_id}/chm-html?path="

    # 匹配 src="..." href="..." 中的相对路径（不含 http/https/#开头）
    def rewrite_attr_match(m: re.Match) -> str:
        attr = m.group(1)  # src or href
        quote = m.group(2)  # " or '
        url = m.group(3)
        # 跳过绝对URL、锚点、data URI
        if url.startswith(
            ("http://", "https://", "#", "data:", "mailto:", "javascript:")
        ):
            return m.group(0)
        # 去掉查询参数（如 style.css?v=1 → style.css）
        clean_url = url.split("?")[0]
        # 拼接：当前 HTML 所在目录 + 相对路径
        full_path = f"{html_dir}/{clean_url}" if html_dir else clean_url
        return f"{attr}={quote}{base}{full_path}{quote}"

    result = re.sub(
        r'(src|href)\s*=\s*(["\'])([^"\']+)\2', rewrite_attr_match, html_content
    )

    # 重写 CSS 中的 url() 引用
    def rewrite_css_url_match(m: re.Match) -> str:
        url = m.group(1).strip().strip("'\"")
        if url.startswith(
            ("http://", "https://", "#", "data:", "mailto:", "javascript:")
        ):
            return m.group(0)
        clean_url = url.split("?")[0]
        full_path = f"{html_dir}/{clean_url}" if html_dir else clean_url
        return f"url({base}{full_path})"

    result = re.sub(r"url\(([^)]+)\)", rewrite_css_url_match, result)
    return result


@router.get("/{doc_id}/{subpath:path}")
async def get_chm_static_fallback(doc_id: str, subpath: str):
    """Fallback for CHM static resources with relative paths that weren't rewritten."""
    if not subpath:
        raise HTTPException(status_code=404)
    metadata = _load_metadata()
    if doc_id not in metadata:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")

    doc = metadata[doc_id]
    if doc.file_type != "chm":
        raise HTTPException(status_code=404, detail="仅支持 CHM 文档")

    stored = Path(doc.stored_path)
    extract_dir = stored.parent / f"{stored.stem}_extracted"
    if not extract_dir.exists():
        raise HTTPException(status_code=404, detail="CHM 解压目录不存在")

    # Search for the file in any subdirectory
    clean_subpath = subpath.split("?")[0]
    candidates = list(extract_dir.rglob(clean_subpath))
    if not candidates:
        raise HTTPException(status_code=404, detail=f"文件不存在: {subpath}")

    # Use the first match
    file_path = candidates[0].resolve()
    if not str(file_path).startswith(str(extract_dir.resolve())):
        raise HTTPException(status_code=403, detail="非法路径")

    from fastapi.responses import FileResponse
    import mimetypes

    mime_type, _ = mimetypes.guess_type(str(file_path))
    return FileResponse(
        path=str(file_path), media_type=mime_type or "application/octet-stream"
    )
