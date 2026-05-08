"""Resolution CRUD, embedding, and relation-link logic."""

import logging
from datetime import datetime
from uuid import uuid4

from ..graph import queries as gq
from ..graph.extract import find_and_create_links
from ..models.meeting import Resolution, ResolutionCreate, ResolutionUpdate
from ..rag.embeddings import embed_texts
from ..resolution_store import load_resolutions, save_resolutions

logger = logging.getLogger(__name__)


# ── helpers ──


def list_for_meeting(meeting_id: str) -> list[Resolution]:
    data = load_resolutions()
    return [Resolution(**r) for r in data.values() if r.get("meeting_id") == meeting_id]


def list_active_for_project(project_id: str) -> list[Resolution]:
    data = load_resolutions()
    return [
        Resolution(**r)
        for r in data.values()
        if r.get("project_id") == project_id and r.get("status") == "active"
    ]


def count_for_meeting(meeting_id: str) -> int:
    data = load_resolutions()
    return sum(1 for r in data.values() if r.get("meeting_id") == meeting_id)


# ── CRUD ──


async def create(
    meeting_id: str, project_id: str, req: ResolutionCreate
) -> Resolution:
    res_id = f"res_{uuid4().hex[:8]}"
    now = datetime.now().isoformat()

    data = load_resolutions()
    existing = [r for r in data.values() if r.get("meeting_id") == meeting_id]
    next_index = max((r.get("index", 0) for r in existing), default=0) + 1

    resolution = Resolution(
        id=res_id,
        meeting_id=meeting_id,
        project_id=project_id,
        content=req.content,
        index=req.index if req.index and req.index > 0 else next_index,
        status=req.status,
        source_doc_id=req.source_doc_id,
        created_at=now,
    )
    data[res_id] = resolution.model_dump()
    save_resolutions(data)

    await gq.create_resolution(
        res_id, meeting_id, project_id, req.content, req.index,
        req.status, req.source_doc_id, now,
    )
    await gq.add_meeting_resolution(meeting_id, res_id)

    # embedding
    try:
        emb = embed_texts([req.content])[0]
        await gq.update_resolution(res_id, embedding=emb)
        data = load_resolutions()
        if res_id in data:
            data[res_id]["_embedded"] = True
            save_resolutions(data)
    except Exception as e:
        logger.warning("Embedding failed for %s: %s", res_id, e)

    return resolution


async def update(resolution_id: str, req: ResolutionUpdate) -> Resolution:
    data = load_resolutions()
    if resolution_id not in data:
        raise KeyError("决议不存在")
    r = data[resolution_id]
    updates: dict = {}
    if req.content is not None:
        r["content"] = req.content
        updates["content"] = req.content
    if req.status is not None:
        r["status"] = req.status
        updates["status"] = req.status
    if req.index is not None:
        r["index"] = req.index
        updates["idx"] = req.index
    save_resolutions(data)
    if updates:
        await gq.update_resolution(resolution_id, **updates)
    return Resolution(**r)


async def delete(resolution_id: str) -> None:
    data = load_resolutions()
    if resolution_id not in data:
        raise KeyError("决议不存在")

    # Collect superseded targets before deleting
    superseded_targets: set[str] = set()
    for rel_type in ("SUPERSEDES", "AMENDS", "SUPPLEMENTS"):
        try:
            rows = await gq.exec_query(
                f"MATCH (a:Resolution)-[e:{rel_type}]->(b:Resolution) "
                "WHERE a.id = $id RETURN b.id",
                {"id": resolution_id},
            )
            for row in rows:
                superseded_targets.add(row[0])
        except Exception:
            logger.debug("Edge query failed for %s/%s", resolution_id, rel_type)

    del data[resolution_id]
    save_resolutions(data)
    await gq.delete_resolution(resolution_id)

    # Reset orphaned superseded
    for tid in superseded_targets:
        if tid not in data:
            continue
        still_superseded = False
        try:
            rows = await gq.exec_query(
                "MATCH (a:Resolution)-[e:SUPERSEDES]->(b:Resolution) "
                "WHERE b.id = $id RETURN a.id",
                {"id": tid},
            )
            still_superseded = len(rows) > 0
        except Exception:
            logger.debug("SUPERSEDES check failed for %s", tid)
        if not still_superseded:
            data[tid]["status"] = "active"
            save_resolutions(data)
            try:
                await gq.update_resolution(tid, status="active")
            except Exception:
                logger.debug("Status update failed for %s", tid)


# ── import helpers ──


async def create_with_embedding(
    meeting_id: str, project_id: str, ext: dict
) -> Resolution:
    """Create a single resolution from LLM-extracted data, with embedding."""
    res_id = f"res_{uuid4().hex[:8]}"
    now = datetime.now().isoformat()

    resolution = Resolution(
        id=res_id,
        meeting_id=meeting_id,
        project_id=project_id,
        content=ext["content"],
        index=ext.get("index", 0),
        status="active",
        created_at=now,
    )

    all_res = load_resolutions()
    all_res[res_id] = resolution.model_dump()
    save_resolutions(all_res)

    try:
        emb = embed_texts([ext["content"]])[0]
    except Exception as e:
        logger.warning("Embedding failed for %s: %s", res_id, e)
        emb = None

    await gq.create_resolution(
        res_id, meeting_id, project_id, ext["content"],
        ext.get("index", 0), "active", None, now, embedding=emb,
    )
    await gq.add_meeting_resolution(meeting_id, res_id)

    ext["id"] = res_id
    ext["meeting_id"] = meeting_id
    ext["project_id"] = project_id

    return resolution


async def batch_create_and_link(
    extracted: list[dict],
    meeting_id: str,
    project_id: str,
) -> tuple[list[dict], list[dict]]:
    """Create resolutions from extracted data, then find cross-meeting links.

    Returns (resolutions_data, relations).
    """
    resolutions_data = []
    for ext in extracted:
        res = await create_with_embedding(meeting_id, project_id, ext)
        resolutions_data.append(res.model_dump())

    relations = await find_and_create_links(extracted, project_id, meeting_id)
    return resolutions_data, relations


async def clear_for_meeting(meeting_id: str) -> int:
    """Delete all resolutions for *meeting_id* from JSON + Kùzu.

    Resets orphaned superseded resolutions back to active.
    Returns count deleted.
    """
    data = load_resolutions()
    res_ids = [rid for rid, r in data.items() if r.get("meeting_id") == meeting_id]

    # Collect superseded targets
    superseded_targets: set[str] = set()
    for rid in res_ids:
        for rel_type in ("SUPERSEDES", "AMENDS", "SUPPLEMENTS"):
            try:
                rows = await gq.exec_query(
                    f"MATCH (a:Resolution)-[e:{rel_type}]->(b:Resolution) "
                    "WHERE a.id = $id RETURN b.id",
                    {"id": rid},
                )
                for row in rows:
                    superseded_targets.add(row[0])
            except Exception:
                logger.debug("Edge query failed for %s/%s", rid, rel_type)

    for rid in res_ids:
        await gq.delete_resolution(rid)
        del data[rid]

    # Reset orphaned superseded
    for tid in superseded_targets:
        if tid not in data:
            continue
        still_superseded = False
        try:
            rows = await gq.exec_query(
                "MATCH (a:Resolution)-[e:SUPERSEDES]->(b:Resolution) "
                "WHERE b.id = $id RETURN a.id",
                {"id": tid},
            )
            still_superseded = len(rows) > 0
        except Exception:
            logger.debug("SUPERSEDES check failed for %s", tid)
        if not still_superseded:
            data[tid]["status"] = "active"
            try:
                await gq.update_resolution(tid, status="active")
            except Exception:
                logger.debug("Status update failed for %s", tid)

    save_resolutions(data)
    return len(res_ids)
