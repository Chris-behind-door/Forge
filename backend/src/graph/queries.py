"""
Cypher query wrappers for Kùzu graph operations.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .db import get_conn, get_lock

logger = logging.getLogger(__name__)


def _exec_sync(cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    conn = get_conn()
    result = conn.execute(cypher, parameters=params or {})
    rows = []
    while result.has_next():
        rows.append(result.get_next())
    # Kùzu returns tuples; convert column names from result
    # For simplicity, return raw lists — callers handle structure
    return rows


async def exec_query(cypher: str, params: dict[str, Any] | None = None) -> list[Any]:
    async with get_lock():
        return await asyncio.to_thread(_exec_sync, cypher, params)


# ---- Resolution CRUD ----

async def create_resolution(res_id: str, meeting_id: str, project_id: str,
                            content: str, idx: int, status: str = "active",
                            source_doc_id: str | None = None,
                            created_at: str = "") -> None:
    await exec_query(
        """CREATE (r:Resolution {
            id: $id, meeting_id: $meeting_id, project_id: $project_id,
            content: $content, idx: $idx, status: $status,
            source_doc_id: $source_doc_id, created_at: $created_at
        })""",
        {"id": res_id, "meeting_id": meeting_id, "project_id": project_id,
         "content": content, "idx": idx, "status": status,
         "source_doc_id": source_doc_id or "", "created_at": created_at},
    )


async def get_resolution(res_id: str) -> dict[str, Any] | None:
    rows = await exec_query(
        "MATCH (r:Resolution) WHERE r.id = $id RETURN r.*",
        {"id": res_id},
    )
    if rows:
        return rows[0]
    return None


async def update_resolution(res_id: str, **kwargs: Any) -> None:
    if not kwargs:
        return
    sets = ", ".join(f"r.{k} = ${k}" for k in kwargs)
    params = {"id": res_id, **kwargs}
    await exec_query(f"MATCH (r:Resolution) WHERE r.id = $id SET {sets}", params)


async def delete_resolution(res_id: str) -> None:
    # Also delete all relation edges connected to this resolution
    for rel_type in ("SUPERSEDES", "AMENDS", "SUPPLEMENTS"):
        await exec_query(
            f"MATCH (a:Resolution)-[e:{rel_type}]-(b:Resolution) "
            "WHERE a.id = $id OR b.id = $id DELETE e",
            {"id": res_id},
        )
    await exec_query(
        "MATCH (r:Resolution) WHERE r.id = $id DELETE r",
        {"id": res_id},
    )


# ---- Relations ----

async def create_relation(from_id: str, to_id: str, rel_type: str,
                          meeting_id: str = "", reason: str = "",
                          change_summary: str = "",
                          supplement_content: str = "") -> None:
    extra_fields = {"meeting_id": meeting_id}
    if rel_type == "SUPERSEDES":
        extra_fields["reason"] = reason
    elif rel_type == "AMENDS":
        extra_fields["change_summary"] = change_summary
    elif rel_type == "SUPPLEMENTS":
        extra_fields["supplement_content"] = supplement_content

    fields = ", ".join(f"{k}: ${k}" for k in extra_fields)
    params = {"from_id": from_id, "to_id": to_id, **extra_fields}
    await exec_query(
        f"MATCH (a:Resolution), (b:Resolution) "
        f"WHERE a.id = $from_id AND b.id = $to_id "
        f"CREATE (a)-[:{rel_type} {{{fields}}}]->(b)",
        params,
    )


async def delete_relation(from_id: str, to_id: str, rel_type: str) -> None:
    await exec_query(
        f"MATCH (a:Resolution)-[e:{rel_type}]->(b:Resolution) "
        "WHERE a.id = $from_id AND b.id = $to_id DELETE e",
        {"from_id": from_id, "to_id": to_id},
    )


# ---- Chain query ----

async def get_resolution_chain(res_id: str) -> list[dict[str, Any]]:
    """Get all resolutions connected to this one via SUPERSEDES/AMENDS/SUPPLEMENTS."""
    chain = []
    for rel_type in ("SUPERSEDES", "AMENDS", "SUPPLEMENTS"):
        # Outgoing: this resolution -> other
        rows = await exec_query(
            f"MATCH (a:Resolution)-[e:{rel_type}]->(b:Resolution) "
            "WHERE a.id = $id RETURN b.id, b.content, b.meeting_id, b.status, e",
            {"id": res_id},
        )
        for row in rows:
            chain.append({
                "from_id": res_id, "to_id": row[0],
                "relation_type": rel_type, "direction": "outgoing",
                "to_content": row[1], "to_meeting_id": row[2], "to_status": row[3],
            })
        # Incoming: other -> this resolution
        rows = await exec_query(
            f"MATCH (a:Resolution)-[e:{rel_type}]->(b:Resolution) "
            "WHERE b.id = $id RETURN a.id, a.content, a.meeting_id, a.status, e",
            {"id": res_id},
        )
        for row in rows:
            chain.append({
                "from_id": row[0], "to_id": res_id,
                "relation_type": rel_type, "direction": "incoming",
                "from_content": row[1], "from_meeting_id": row[2], "from_status": row[3],
            })
    return chain


# ---- Project graph ----

async def get_project_graph(project_id: str) -> dict[str, Any]:
    """Get all resolutions and edges for a project."""
    nodes = await exec_query(
        "MATCH (r:Resolution) WHERE r.project_id = $pid "
        "RETURN r.id, r.content, r.meeting_id, r.status",
        {"pid": project_id},
    )
    edges = []
    for rel_type in ("SUPERSEDES", "AMENDS", "SUPPLEMENTS"):
        rows = await exec_query(
            f"MATCH (a:Resolution)-[e:{rel_type}]->(b:Resolution) "
            "WHERE a.project_id = $pid "
            "RETURN a.id, b.id, e",
            {"pid": project_id},
        )
        for row in rows:
            edges.append({"from": row[0], "to": row[1], "type": rel_type})
    return {
        "nodes": [{"id": n[0], "content": n[1], "meeting_id": n[2], "status": n[3]}
                  for n in nodes],
        "edges": edges,
    }


# ---- Project/Meeting containment ----

async def add_project_meeting(project_id: str, meeting_id: str) -> None:
    await exec_query(
        "MATCH (p:Project), (m:Meeting) WHERE p.id = $pid AND m.id = $mid "
        "CREATE (p)-[:CONTAINS_MEETING]->(m)",
        {"pid": project_id, "mid": meeting_id},
    )


async def add_meeting_resolution(meeting_id: str, resolution_id: str) -> None:
    await exec_query(
        "MATCH (m:Meeting), (r:Resolution) WHERE m.id = $mid AND r.id = $rid "
        "CREATE (m)-[:CONTAINS_RESOLUTION]->(r)",
        {"mid": meeting_id, "rid": resolution_id},
    )
