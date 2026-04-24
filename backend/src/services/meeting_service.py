"""Meeting CRUD, file import, and re-extract logic."""

import logging
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from ..graph import queries as gq
from ..models.meeting import Meeting, MeetingCreate, MeetingUpdate
from ..services.json_store import load_json, save_json
from ..services.resolution_service import batch_create_and_link, clear_for_meeting
from ..graph.extract import extract_resolutions

logger = logging.getLogger(__name__)

DATA_DIR = Path.home() / ".engineer_assistant" / "data"
MEETINGS_FILE = DATA_DIR / "meetings.json"

_SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".doc", ".docx"}


# ── JSON persistence ──


def _load_meetings() -> dict[str, dict]:
    return load_json(MEETINGS_FILE)


def _save_meetings(data: dict) -> None:
    save_json(MEETINGS_FILE, data)


# ── CRUD ──


async def create(project_id: str, req: MeetingCreate) -> Meeting:
    meeting_id = f"mtg_{uuid4().hex[:8]}"
    now = datetime.now().isoformat()
    meeting = Meeting(
        id=meeting_id, project_id=project_id, title=req.title, date=req.date,
        raw_text=req.raw_text, source_doc_id=req.source_doc_id, created_at=now,
    )
    meetings = _load_meetings()
    meetings[meeting_id] = meeting.model_dump()
    _save_meetings(meetings)

    await gq.exec_query(
        "CREATE (m:Meeting {id: $id, project_id: $pid, title: $title, date: $date, "
        "summary: $summary, source_doc_id: $sdoc, raw_text: $raw, created_at: $cat})",
        {"id": meeting_id, "pid": project_id, "title": req.title, "date": req.date,
         "summary": "", "sdoc": req.source_doc_id or "", "raw": req.raw_text, "cat": now},
    )
    await gq.add_project_meeting(project_id, meeting_id)
    return meeting


def get(meeting_id: str) -> Meeting:
    meetings = _load_meetings()
    if meeting_id not in meetings:
        raise HTTPException(status_code=404, detail="会议不存在")
    return Meeting(**meetings[meeting_id])


async def update(meeting_id: str, req: MeetingUpdate) -> Meeting:
    meetings = _load_meetings()
    if meeting_id not in meetings:
        raise HTTPException(status_code=404, detail="会议不存在")
    m = meetings[meeting_id]
    if req.title is not None:
        m["title"] = req.title
    if req.date is not None:
        m["date"] = req.date
    if req.raw_text is not None:
        m["raw_text"] = req.raw_text
    if req.summary is not None:
        m["summary"] = req.summary
    _save_meetings(meetings)
    await gq.exec_query(
        "MATCH (m:Meeting) WHERE m.id = $id SET m.title = $title, m.date = $date, "
        "m.raw_text = $raw, m.summary = $summary",
        {"id": meeting_id, "title": m["title"], "date": m["date"],
         "raw": m["raw_text"], "summary": m["summary"]},
    )
    return Meeting(**m)


async def delete(meeting_id: str) -> dict:
    meetings = _load_meetings()
    if meeting_id not in meetings:
        raise HTTPException(status_code=404, detail="会议不存在")

    # Cascade delete resolutions with orphan-superseded recovery
    from ..services.resolution_service import clear_for_meeting
    deleted_count = await clear_for_meeting(meeting_id)

    # Delete graph nodes
    await gq.exec_query(
        "MATCH (m:Meeting)-[e:CONTAINS_RESOLUTION]->(r:Resolution) "
        "WHERE m.id = $id DELETE e",
        {"id": meeting_id},
    )
    await gq.exec_query(
        "MATCH (p:Project)-[e:CONTAINS_MEETING]->(m:Meeting) "
        "WHERE m.id = $id DELETE e",
        {"id": meeting_id},
    )
    await gq.exec_query(
        "MATCH (m:Meeting) WHERE m.id = $id DELETE m",
        {"id": meeting_id},
    )

    del meetings[meeting_id]
    _save_meetings(meetings)
    return {
        "status": "deleted",
        "id": meeting_id,
        "deleted_resolutions": deleted_count,
    }


def list_for_project(project_id: str) -> list[Meeting]:
    meetings = _load_meetings()
    return [Meeting(**m) for m in meetings.values() if m.get("project_id") == project_id]


# ── File import sub-steps ──


def _validate_import_file(filename: str, file_content: bytes) -> str:
    """Validate uploaded file; returns suffix."""
    suffix = Path(filename).suffix.lower()
    if suffix not in _SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {suffix}，支持: {', '.join(_SUPPORTED_EXTENSIONS)}",
        )
    return suffix


def _check_import_duplicate(project_id: str, title: str, filename: str, file_size: int) -> None:
    """Raise 409 if the same file was already imported."""
    meetings = _load_meetings()
    for m in meetings.values():
        if (
            m.get("project_id") == project_id
            and m.get("title") == (title or Path(filename).stem)
            and m.get("_import_file_size") == file_size
        ):
            raise HTTPException(
                status_code=409,
                detail=f"该文件（{filename}，{file_size} 字节）已导入过到该项目",
            )


def _extract_text_from_file(file_path: Path, suffix: str) -> str:
    """Extract plain text from an uploaded file."""
    if suffix in (".txt", ".md"):
        return file_path.read_text(encoding="utf-8", errors="replace")
    elif suffix == ".pdf":
        from ..parsers.pdf import parse_pdf
        chunks = parse_pdf(str(file_path))
        return "\n\n".join(c["text"] for c in chunks)
    elif suffix in (".doc", ".docx"):
        try:
            import docx
            doc = docx.Document(str(file_path))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            raise HTTPException(
                status_code=400,
                detail="Word 文档解析需要 python-docx 库，请运行: pip install python-docx",
            )
    else:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {suffix}")


async def _create_meeting_record(
    project_id: str, title: str, date: str, raw_text: str,
    filename: str, file_size: int, *, status: str = "active",
) -> Meeting:
    """Persist a new meeting with import metadata."""
    meeting_id = f"mtg_{uuid4().hex[:8]}"
    now = datetime.now().isoformat()
    meeting = Meeting(
        id=meeting_id, project_id=project_id, title=title, date=date,
        raw_text=raw_text, created_at=now, status=status,
    )
    meetings = _load_meetings()
    meeting_data = meeting.model_dump()
    meeting_data["_import_filename"] = filename
    meeting_data["_import_file_size"] = file_size
    meetings[meeting_id] = meeting_data
    _save_meetings(meetings)

    await gq.exec_query(
        "CREATE (m:Meeting {id: $id, project_id: $pid, title: $title, date: $date, "
        "summary: $summary, source_doc_id: $sdoc, raw_text: $raw, created_at: $cat, status: $status})",
        {"id": meeting_id, "pid": project_id, "title": title, "date": date,
         "summary": "", "sdoc": "", "raw": raw_text, "cat": now, "status": status},
    )
    await gq.add_project_meeting(project_id, meeting_id)
    return meeting


async def import_meeting(
    project_id: str, date: str, title: str, filename: str, file_content: bytes,
) -> dict:
    """Async import: validate → dedup → create queued meeting → enqueue task → return immediately."""
    if not date:
        raise HTTPException(status_code=400, detail="会议日期为必填字段")

    suffix = _validate_import_file(filename, file_content)
    file_size = len(file_content)
    _check_import_duplicate(project_id, title, filename, file_size)

    meeting_title = title or Path(filename).stem

    # Save file to temp location for later processing
    tmp_path = Path(tempfile.mktemp(suffix=suffix))
    tmp_path.write_bytes(file_content)

    # Create meeting record with status=queued
    from .import_worker import ImportTask, get_import_queue
    meeting = await _create_meeting_record(
        project_id, meeting_title, date, "", filename, file_size,
        status="queued",
    )

    # Enqueue
    task = ImportTask(
        meeting_id=meeting.id,
        project_id=project_id,
        tmp_path=tmp_path,
        suffix=suffix,
    )
    get_import_queue().enqueue(task)

    return {
        "meeting_id": meeting.id,
        "status": "queued",
        "message": "已加入处理队列",
    }


async def re_extract(meeting_id: str) -> dict:
    """Re-extract resolutions for an existing meeting."""
    meetings = _load_meetings()
    if meeting_id not in meetings:
        raise HTTPException(status_code=404, detail="会议不存在")
    meeting = meetings[meeting_id]
    raw_text = meeting.get("raw_text", "")
    project_id = meeting["project_id"]

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="该会议没有纪要文本")

    deleted_count = await clear_for_meeting(meeting_id)
    logger.info("Cleared %d resolutions for meeting %s", deleted_count, meeting_id)

    extracted = await extract_resolutions(raw_text, meeting.get("date", ""))
    if not extracted:
        return {"meeting_id": meeting_id, "resolutions": [], "relations": [],
                "cleared": deleted_count}

    resolutions_data, relations = await batch_create_and_link(
        extracted, meeting_id, project_id,
    )
    return {
        "meeting_id": meeting_id,
        "resolutions": resolutions_data,
        "relations": relations,
        "cleared": deleted_count,
    }
