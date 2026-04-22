"""
Meeting, Resolution, and Relation API routes.
"""

import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from ..models.meeting import (
    Meeting, MeetingCreate, MeetingUpdate,
    Resolution, ResolutionCreate, ResolutionUpdate,
    RelationCreate,
)
from ..graph import queries as gq
from ..graph.extract import extract_resolutions, find_and_create_links
from ..rag.embeddings import embed_texts

logger = logging.getLogger(__name__)

router = APIRouter(tags=["meetings"])

DATA_DIR = Path.home() / ".engineer_assistant" / "data"
MEETINGS_FILE = DATA_DIR / "meetings.json"
RESOLUTIONS_FILE = DATA_DIR / "resolutions.json"


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_meetings() -> dict[str, dict]:
    _ensure_dir()
    if not MEETINGS_FILE.exists():
        return {}
    with open(MEETINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_meetings(data: dict) -> None:
    _ensure_dir()
    with open(MEETINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _load_resolutions() -> dict[str, dict]:
    _ensure_dir()
    if not RESOLUTIONS_FILE.exists():
        return {}
    with open(RESOLUTIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_resolutions(data: dict) -> None:
    _ensure_dir()
    with open(RESOLUTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---- Meetings ----

@router.get("/projects/{project_id}/meetings", response_model=list[Meeting])
async def list_meetings(project_id: str) -> list[Meeting]:
    meetings = _load_meetings()
    return [Meeting(**m) for m in meetings.values() if m.get("project_id") == project_id]


@router.post("/projects/{project_id}/meetings", response_model=Meeting)
async def create_meeting(project_id: str, req: MeetingCreate) -> Meeting:
    meeting_id = f"mtg_{uuid4().hex[:8]}"
    now = datetime.now().isoformat()
    meeting = Meeting(
        id=meeting_id, project_id=project_id,
        title=req.title, date=req.date,
        raw_text=req.raw_text, source_doc_id=req.source_doc_id,
        created_at=now,
    )
    meetings = _load_meetings()
    meetings[meeting_id] = meeting.model_dump()
    _save_meetings(meetings)

    # Kùzu node + containment edge
    await gq.exec_query(
        "CREATE (m:Meeting {id: $id, project_id: $pid, title: $title, date: $date, "
        "summary: $summary, source_doc_id: $sdoc, raw_text: $raw, created_at: $cat})",
        {"id": meeting_id, "pid": project_id, "title": req.title, "date": req.date,
         "summary": "", "sdoc": req.source_doc_id or "", "raw": req.raw_text, "cat": now},
    )
    await gq.add_project_meeting(project_id, meeting_id)

    return meeting


@router.get("/meetings/{meeting_id}", response_model=Meeting)
async def get_meeting(meeting_id: str) -> Meeting:
    meetings = _load_meetings()
    if meeting_id not in meetings:
        raise HTTPException(status_code=404, detail="会议不存在")
    return Meeting(**meetings[meeting_id])


@router.put("/meetings/{meeting_id}", response_model=Meeting)
async def update_meeting(meeting_id: str, req: MeetingUpdate) -> Meeting:
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


@router.delete("/meetings/{meeting_id}")
async def delete_meeting(meeting_id: str) -> dict:
    meetings = _load_meetings()
    if meeting_id not in meetings:
        raise HTTPException(status_code=404, detail="会议不存在")

    # Cascade delete resolutions
    resolutions = _load_resolutions()
    res_ids = [rid for rid, r in resolutions.items() if r.get("meeting_id") == meeting_id]
    for rid in res_ids:
        await gq.delete_resolution(rid)
        del resolutions[rid]
    _save_resolutions(resolutions)

    # Delete Meeting node and edges in Kùzu
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

    return {"status": "deleted", "id": meeting_id, "deleted_resolutions": len(res_ids)}


# ---- Resolutions ----

@router.get("/meetings/{meeting_id}/resolutions", response_model=list[Resolution])
async def list_resolutions(meeting_id: str) -> list[Resolution]:
    resolutions = _load_resolutions()
    return [Resolution(**r) for r in resolutions.values() if r.get("meeting_id") == meeting_id]


@router.post("/meetings/{meeting_id}/resolutions", response_model=Resolution)
async def create_resolution(meeting_id: str, req: ResolutionCreate) -> Resolution:
    meetings = _load_meetings()
    if meeting_id not in meetings:
        raise HTTPException(status_code=404, detail="会议不存在")
    project_id = meetings[meeting_id]["project_id"]

    res_id = f"res_{uuid4().hex[:8]}"
    now = datetime.now().isoformat()
    # Auto-calculate index if not provided or invalid
    resolutions = _load_resolutions()
    existing = [r for r in resolutions.values() if r.get("meeting_id") == meeting_id]
    next_index = max((r.get("index", 0) for r in existing), default=0) + 1
    resolution = Resolution(
        id=res_id, meeting_id=meeting_id, project_id=project_id,
        content=req.content, index=req.index if req.index and req.index > 0 else next_index,
        status=req.status, source_doc_id=req.source_doc_id, created_at=now,
    )
    resolutions = _load_resolutions()
    resolutions[res_id] = resolution.model_dump()
    _save_resolutions(resolutions)

    await gq.create_resolution(
        res_id, meeting_id, project_id, req.content, req.index,
        req.status, req.source_doc_id, now,
    )
    await gq.add_meeting_resolution(meeting_id, res_id)

    # Generate embedding asynchronously
    try:
        emb = embed_texts([req.content])[0]
        await gq.update_resolution(res_id, embedding=emb)
        # Store in JSON too
        resolutions = _load_resolutions()
        if res_id in resolutions:
            # Don't store full 512-dim vector in JSON, just mark as embedded
            resolutions[res_id]["_embedded"] = True
            _save_resolutions(resolutions)
    except Exception as e:
        logger.warning("Failed to generate embedding for resolution %s: %s", res_id, e)

    return resolution


@router.put("/resolutions/{resolution_id}", response_model=Resolution)
async def update_resolution(resolution_id: str, req: ResolutionUpdate) -> Resolution:
    resolutions = _load_resolutions()
    if resolution_id not in resolutions:
        raise HTTPException(status_code=404, detail="决议不存在")
    r = resolutions[resolution_id]
    updates = {}
    if req.content is not None:
        r["content"] = req.content
        updates["content"] = req.content
    if req.status is not None:
        r["status"] = req.status
        updates["status"] = req.status
    if req.index is not None:
        r["index"] = req.index
        updates["idx"] = req.index
    _save_resolutions(resolutions)

    if updates:
        await gq.update_resolution(resolution_id, **updates)
    return Resolution(**r)


@router.delete("/resolutions/{resolution_id}")
async def delete_resolution_endpoint(resolution_id: str) -> dict:
    resolutions = _load_resolutions()
    if resolution_id not in resolutions:
        raise HTTPException(status_code=404, detail="决议不存在")
    del resolutions[resolution_id]
    _save_resolutions(resolutions)
    await gq.delete_resolution(resolution_id)
    return {"status": "deleted", "id": resolution_id}


# ---- Relations ----

@router.post("/resolutions/relations")
async def create_relation(req: RelationCreate) -> dict:
    valid_types = {"SUPERSEDES", "AMENDS", "SUPPLEMENTS"}
    if req.relation_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"关联类型必须是 {valid_types} 之一")

    await gq.create_relation(
        req.from_id, req.to_id, req.relation_type,
        req.meeting_id, req.reason, req.change_summary, req.supplement_content,
    )

    # Update status if SUPERSEDES
    if req.relation_type == "SUPERSEDES":
        resolutions = _load_resolutions()
        if req.to_id in resolutions:
            resolutions[req.to_id]["status"] = "superseded"
            _save_resolutions(resolutions)
            await gq.update_resolution(req.to_id, status="superseded")

    return {"status": "created", "from": req.from_id, "to": req.to_id, "type": req.relation_type}


@router.delete("/resolutions/relations")
async def delete_relation(from_id: str, to_id: str, relation_type: str) -> dict:
    await gq.delete_relation(from_id, to_id, relation_type)
    return {"status": "deleted"}


# ---- Queries ----

@router.get("/resolutions/{resolution_id}/chain")
async def get_resolution_chain(resolution_id: str) -> dict:
    chain = await gq.get_resolution_chain(resolution_id)
    return {"target_id": resolution_id, "chain": chain}


@router.get("/projects/{project_id}/resolutions/active", response_model=list[Resolution])
async def list_active_resolutions(project_id: str) -> list[Resolution]:
    resolutions = _load_resolutions()
    return [Resolution(**r) for r in resolutions.values()
            if r.get("project_id") == project_id and r.get("status") == "active"]


@router.get("/projects/{project_id}/graph")
async def get_project_graph(project_id: str) -> dict:
    return await gq.get_project_graph(project_id)


# ---- File Upload + Extraction ----

# Supported file extensions and their text extraction
_SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".doc", ".docx"}


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


@router.post("/projects/{project_id}/meetings/import")
async def import_meeting_with_file(
    project_id: str,
    date: str = Form(...),
    title: str = Form(""),
    file: UploadFile = File(...),
) -> dict:
    """
    Upload a meeting notes file (PDF/TXT/MD/DOC/DOCX), extract text,
    create meeting, then auto-extract resolutions and link to existing ones.
    """
    if not date:
        raise HTTPException(status_code=400, detail="会议日期为必填字段")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {suffix}，支持: {', '.join(_SUPPORTED_EXTENSIONS)}",
        )

    # Save uploaded file to temp, extract text
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        raw_text = _extract_text_from_file(tmp_path, suffix)
    finally:
        tmp_path.unlink(missing_ok=True)

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="文件中未提取到有效文本")

    # Use filename as title if not provided
    meeting_title = title or Path(file.filename or "会议纪要").stem

    # Create meeting
    meeting_id = f"mtg_{uuid4().hex[:8]}"
    now = datetime.now().isoformat()
    meeting = Meeting(
        id=meeting_id, project_id=project_id,
        title=meeting_title, date=date,
        raw_text=raw_text, created_at=now,
    )
    meetings = _load_meetings()
    meetings[meeting_id] = meeting.model_dump()
    _save_meetings(meetings)

    await gq.exec_query(
        "CREATE (m:Meeting {id: $id, project_id: $pid, title: $title, date: $date, "
        "summary: $summary, source_doc_id: $sdoc, raw_text: $raw, created_at: $cat})",
        {"id": meeting_id, "pid": project_id, "title": meeting_title, "date": date,
         "summary": "", "sdoc": "", "raw": raw_text, "cat": now},
    )
    await gq.add_project_meeting(project_id, meeting_id)

    # Step 1: Extract resolutions via LLM
    extracted = await extract_resolutions(raw_text, date)

    if not extracted:
        return {
            "meeting": meeting.model_dump(),
            "resolutions": [],
            "relations": [],
            "message": "未提取到决议",
        }

    # Step 2: Create resolution nodes + embeddings
    resolutions_data = []
    for ext in extracted:
        res_id = f"res_{uuid4().hex[:8]}"
        ext["id"] = res_id
        ext["meeting_id"] = meeting_id
        ext["project_id"] = project_id

        resolution = Resolution(
            id=res_id, meeting_id=meeting_id, project_id=project_id,
            content=ext["content"], index=ext.get("index", 0),
            status="active", created_at=now,
        )
        resolutions_data.append(resolution.model_dump())

        # Save to JSON
        all_res = _load_resolutions()
        all_res[res_id] = resolution.model_dump()
        _save_resolutions(all_res)

        # Generate embedding
        try:
            emb = embed_texts([ext["content"]])[0]
        except Exception as e:
            logger.warning("Embedding failed for %s: %s", res_id, e)
            emb = None

        await gq.create_resolution(
            res_id, meeting_id, project_id, ext["content"],
            ext.get("index", 0), "active", None, now,
            embedding=emb,
        )
        await gq.add_meeting_resolution(meeting_id, res_id)

    # Step 3: Find cross-meeting links
    relations = await find_and_create_links(
        extracted, project_id, meeting_id,
    )

    return {
        "meeting": meeting.model_dump(),
        "resolutions": resolutions_data,
        "relations": relations,
        "message": f"提取了 {len(resolutions_data)} 条决议，建立了 {len(relations)} 条关联",
    }


@router.post("/meetings/{meeting_id}/extract")
async def extract_meeting_resolutions(meeting_id: str) -> dict:
    """Extract resolutions from an existing meeting's raw_text."""
    meetings = _load_meetings()
    if meeting_id not in meetings:
        raise HTTPException(status_code=404, detail="会议不存在")
    meeting = meetings[meeting_id]
    raw_text = meeting.get("raw_text", "")
    project_id = meeting["project_id"]

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="该会议没有纪要文本")

    extracted = await extract_resolutions(raw_text, meeting.get("date", ""))

    if not extracted:
        return {"meeting_id": meeting_id, "resolutions": [], "relations": []}

    now = datetime.now().isoformat()
    resolutions_data = []
    for ext in extracted:
        res_id = f"res_{uuid4().hex[:8]}"
        ext["id"] = res_id

        resolution = Resolution(
            id=res_id, meeting_id=meeting_id, project_id=project_id,
            content=ext["content"], index=ext.get("index", 0),
            status="active", created_at=now,
        )
        resolutions_data.append(resolution.model_dump())

        all_res = _load_resolutions()
        all_res[res_id] = resolution.model_dump()
        _save_resolutions(all_res)

        try:
            emb = embed_texts([ext["content"]])[0]
        except Exception:
            emb = None

        await gq.create_resolution(
            res_id, meeting_id, project_id, ext["content"],
            ext.get("index", 0), "active", None, now,
            embedding=emb,
        )
        await gq.add_meeting_resolution(meeting_id, res_id)

    relations = await find_and_create_links(extracted, project_id, meeting_id)

    return {
        "meeting_id": meeting_id,
        "resolutions": resolutions_data,
        "relations": relations,
    }
