"""Meeting, Resolution, and Relation API routes — thin HTTP layer."""

import logging
from collections import defaultdict

from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from ..models.meeting import (
    Meeting, MeetingCreate, MeetingUpdate,
    Resolution, ResolutionCreate, ResolutionUpdate,
    RelationCreate,
)
from ..graph import queries as gq
from ..services import meeting_service as ms
from ..services import resolution_service as rs
from ..resolution_store import load_resolutions, save_resolutions

logger = logging.getLogger(__name__)

router = APIRouter(tags=["meetings"])


# ---- Meetings ----


@router.get("/projects/{project_id}/meetings", response_model=list[Meeting])
async def list_meetings(project_id: str) -> list[Meeting]:
    return ms.list_for_project(project_id)


@router.post("/projects/{project_id}/meetings", response_model=Meeting)
async def create_meeting(project_id: str, req: MeetingCreate) -> Meeting:
    return await ms.create(project_id, req)


@router.get("/meetings/{meeting_id}", response_model=Meeting)
async def get_meeting(meeting_id: str) -> Meeting:
    return ms.get(meeting_id)


@router.put("/meetings/{meeting_id}", response_model=Meeting)
async def update_meeting(meeting_id: str, req: MeetingUpdate) -> Meeting:
    return await ms.update(meeting_id, req)


@router.delete("/meetings/{meeting_id}")
async def delete_meeting(meeting_id: str) -> dict:
    return await ms.delete(meeting_id)


# ---- Resolutions ----


@router.get("/meetings/{meeting_id}/resolutions", response_model=list[Resolution])
async def list_resolutions(meeting_id: str) -> list[Resolution]:
    return rs.list_for_meeting(meeting_id)


@router.post("/meetings/{meeting_id}/resolutions", response_model=Resolution)
async def create_resolution(meeting_id: str, req: ResolutionCreate) -> Resolution:
    meeting = ms.get(meeting_id)
    return await rs.create(meeting_id, meeting.project_id, req)


@router.put("/resolutions/{resolution_id}", response_model=Resolution)
async def update_resolution(resolution_id: str, req: ResolutionUpdate) -> Resolution:
    try:
        return await rs.update(resolution_id, req)
    except KeyError:
        raise HTTPException(status_code=404, detail="决议不存在")


@router.delete("/resolutions/{resolution_id}")
async def delete_resolution_endpoint(resolution_id: str) -> dict:
    try:
        await rs.delete(resolution_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="决议不存在")
    return {"status": "deleted", "id": resolution_id}


# ---- Relations ----


@router.post("/relations")
async def create_relation(req: RelationCreate) -> dict:
    valid_types = {"SUPERSEDES", "AMENDS", "SUPPLEMENTS"}
    if req.relation_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"关联类型必须是 {valid_types} 之一")

    await gq.create_relation(
        req.from_id, req.to_id, req.relation_type,
        req.meeting_id, req.reason, req.change_summary, req.supplement_content,
    )

    if req.relation_type == "SUPERSEDES":
        resolutions = load_resolutions()
        if req.to_id in resolutions:
            resolutions[req.to_id]["status"] = "superseded"
            save_resolutions(resolutions)
            await gq.update_resolution(req.to_id, status="superseded")

    return {"status": "created", "from": req.from_id, "to": req.to_id, "type": req.relation_type}


@router.delete("/relations")
async def delete_relation(from_id: str, to_id: str, relation_type: str) -> dict:
    try:
        await gq.delete_relation(from_id, to_id, relation_type)
    except Exception as e:
        logger.warning("Failed to delete relation %s->%s (%s): %s", from_id, to_id, relation_type, e)
        raise HTTPException(
            status_code=404,
            detail=f"关联不存在或已删除: {from_id} -{relation_type}-> {to_id}",
        ) from None
    return {"status": "deleted"}


# ---- Data Cleanup ----


@router.post("/admin/cleanup-resolutions")
async def cleanup_duplicate_resolutions() -> dict:
    resolutions = load_resolutions()
    groups: dict[tuple[str, int], list[tuple[str, dict]]] = defaultdict(list)
    for rid, r in resolutions.items():
        key = (r.get("meeting_id", ""), r.get("index", 0))
        groups[key].append((rid, r))

    to_remove: list[str] = []
    for key, items in groups.items():
        if len(items) <= 1:
            continue
        items.sort(key=lambda x: x[1].get("created_at", ""), reverse=True)
        for rid, _ in items[1:]:
            to_remove.append(rid)

    for rid in to_remove:
        try:
            await gq.delete_resolution(rid)
        except Exception as e:
            logger.warning("Failed to delete Kùzu node %s during cleanup: %s", rid, e)
        del resolutions[rid]

    save_resolutions(resolutions)
    return {"status": "cleaned", "removed_duplicates": len(to_remove), "removed_ids": to_remove}


# ---- Queries ----


@router.get("/resolutions/{resolution_id}/chain")
async def get_resolution_chain(resolution_id: str) -> dict:
    chain = await gq.get_resolution_chain(resolution_id)
    return {"target_id": resolution_id, "chain": chain}


@router.get("/projects/{project_id}/resolutions/active", response_model=list[Resolution])
async def list_active_resolutions(project_id: str) -> list[Resolution]:
    return rs.list_active_for_project(project_id)


@router.get("/projects/{project_id}/graph")
async def get_project_graph(project_id: str) -> dict:
    return await gq.get_project_graph(project_id)


# ---- File Upload + Extraction ----


@router.post("/projects/{project_id}/meetings/import")
async def import_meeting_with_file(
    project_id: str,
    date: str = Form(...),
    title: str = Form(""),
    file: UploadFile = File(...),
) -> dict:
    filename = file.filename or ""
    file_content = await file.read()
    return await ms.import_meeting(project_id, date, title, filename, file_content)


@router.get("/meetings/{meeting_id}/resolutions/count")
async def count_meeting_resolutions(meeting_id: str) -> dict:
    return {"meeting_id": meeting_id, "count": rs.count_for_meeting(meeting_id)}


@router.post("/meetings/{meeting_id}/extract")
async def extract_meeting_resolutions(meeting_id: str) -> dict:
    return await ms.re_extract(meeting_id)
