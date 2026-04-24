"""CHM HTML query, URL rewriting, and static-resource serving logic."""

import logging
import mimetypes
import re
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from ..services.document_service import _load_metadata

logger = logging.getLogger(__name__)


def get_chm_html(doc_id: str, path: str):
    """Serve an HTML file from an extracted CHM, with rewritten URLs."""
    metadata = _load_metadata()
    if doc_id not in metadata:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")

    doc = metadata[doc_id]
    if doc.file_type != "chm":
        raise HTTPException(status_code=400, detail="仅支持 CHM 文档")
    if not path:
        raise HTTPException(status_code=400, detail="需要指定 path 参数")

    stored = Path(doc.stored_path)
    extract_dir = stored.parent / f"{stored.stem}_extracted"
    if not extract_dir.exists():
        raise HTTPException(status_code=404, detail="CHM 解压目录不存在，请重新导入文档以生成")

    clean_path = path.split("?")[0]
    file_path = (extract_dir / clean_path).resolve()
    if not str(file_path).startswith(str(extract_dir.resolve())):
        raise HTTPException(status_code=403, detail="非法路径")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {clean_path}")

    if file_path.suffix.lower() in (".html", ".htm"):
        raw = file_path.read_bytes()
        from ..parsers.chm import _detect_encoding
        encoding = _detect_encoding(raw)
        content = raw.decode(encoding, errors="replace")
        html_dir = str(Path(clean_path).parent) if "/" in clean_path else ""
        content = rewrite_html_urls(content, doc_id, html_dir)
        return HTMLResponse(content=content)
    else:
        mime_type, _ = mimetypes.guess_type(str(file_path))
        return FileResponse(path=str(file_path), media_type=mime_type or "application/octet-stream")


def get_chm_static(doc_id: str, subpath: str):
    """Fallback for CHM static resources with relative paths."""
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

    clean_subpath = subpath.split("?")[0]
    candidates = list(extract_dir.rglob(clean_subpath))
    if not candidates:
        raise HTTPException(status_code=404, detail=f"文件不存在: {subpath}")

    file_path = candidates[0].resolve()
    if not str(file_path).startswith(str(extract_dir.resolve())):
        raise HTTPException(status_code=403, detail="非法路径")

    mime_type, _ = mimetypes.guess_type(str(file_path))
    return FileResponse(path=str(file_path), media_type=mime_type or "application/octet-stream")


def rewrite_html_urls(html_content: str, doc_id: str, html_dir: str) -> str:
    """Rewrite CHM HTML relative URLs to point at the backend endpoint."""
    base = f"/documents/{doc_id}/chm-html?path="

    def rewrite_attr_match(m: re.Match) -> str:
        attr, quote, url = m.group(1), m.group(2), m.group(3)
        if url.startswith(("http://", "https://", "#", "data:", "mailto:", "javascript:")):
            return m.group(0)
        clean_url = url.split("?")[0]
        full_path = f"{html_dir}/{clean_url}" if html_dir else clean_url
        return f"{attr}={quote}{base}{full_path}{quote}"

    result = re.sub(r'(src|href)\s*=\s*(["\'])([^"\']+)\2', rewrite_attr_match, html_content)

    def rewrite_css_url_match(m: re.Match) -> str:
        url = m.group(1).strip().strip("'\"")
        if url.startswith(("http://", "https://", "#", "data:", "mailto:", "javascript:")):
            return m.group(0)
        clean_url = url.split("?")[0]
        full_path = f"{html_dir}/{clean_url}" if html_dir else clean_url
        return f"url({base}{full_path})"

    result = re.sub(r"url\(([^)]+)\)", rewrite_css_url_match, result)
    return result
