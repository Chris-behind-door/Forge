"""
Project CRUD API routes.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from ..models.project import Project, ProjectCreate, ProjectDetail, ProjectUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])

DATA_DIR = Path.home() / ".engineer_assistant" / "data"
PROJECTS_FILE = DATA_DIR / "projects.json"
MEETINGS_FILE = DATA_DIR / "meetings.json"
RESOLUTIONS_FILE = DATA_DIR / "resolutions.json"


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_projects() -> dict[str, Project]:
    _ensure_dir()
    if not PROJECTS_FILE.exists():
        return {}
    with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {k: Project(**v) for k, v in data.items()}


def _save_projects(projects: dict[str, Project]) -> None:
    _ensure_dir()
    with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
        json.dump({k: v.model_dump() for k, v in projects.items()}, f,
                  indent=2, ensure_ascii=False)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@router.get("")
async def list_projects() -> list[Project]:
    projects = _load_projects()
    return list(projects.values())


@router.post("", response_model=Project)
async def create_project(req: ProjectCreate) -> Project:
    projects = _load_projects()
    project = Project(
        id=f"proj_{uuid4().hex[:8]}",
        name=req.name,
        description=req.description,
        created_at=datetime.now().isoformat(),
    )
    projects[project.id] = project
    _save_projects(projects)

    # Create node in Kùzu
    from ..graph.queries import exec_query
    await exec_query(
        "CREATE (p:Project {id: $id, name: $name, description: $pdesc, created_at: $cat})",
        {"id": project.id, "name": project.name, "pdesc": project.description,
         "cat": project.created_at},
    )
    return project


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(project_id: str) -> ProjectDetail:
    projects = _load_projects()
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="项目不存在")
    proj = projects[project_id]

    meetings_data = _load_json(MEETINGS_FILE)
    resolutions_data = _load_json(RESOLUTIONS_FILE)

    proj_meetings = [m for m in meetings_data.values() if m.get("project_id") == project_id]
    for mtg in proj_meetings:
        mtg["resolution_count"] = sum(
            1 for r in resolutions_data.values() if r.get("meeting_id") == mtg["id"]
        )

    total_res = sum(1 for r in resolutions_data.values() if r.get("project_id") == project_id)

    return ProjectDetail(
        **proj.model_dump(),
        meeting_count=len(proj_meetings),
        resolution_count=total_res,
        meetings=proj_meetings,
    )


@router.put("/{project_id}", response_model=Project)
async def update_project(project_id: str, req: ProjectUpdate) -> Project:
    projects = _load_projects()
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="项目不存在")
    proj = projects[project_id]
    if req.name is not None:
        proj.name = req.name
    if req.description is not None:
        proj.description = req.description
    _save_projects(projects)

    from ..graph.queries import exec_query
    await exec_query(
        "MATCH (p:Project) WHERE p.id = $id SET p.name = $name, p.description = $pdesc",
        {"id": project_id, "name": proj.name, "pdesc": proj.description},
    )
    return proj


@router.delete("/{project_id}")
async def delete_project(project_id: str) -> dict:
    projects = _load_projects()
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="项目不存在")

    # Cascade: remove meetings and resolutions from JSON
    meetings_data = _load_json(MEETINGS_FILE)
    resolutions_data = _load_json(RESOLUTIONS_FILE)
    meeting_ids = {mid for mid, m in meetings_data.items() if m.get("project_id") == project_id}
    for mid in meeting_ids:
        resolutions_data = {rid: r for rid, r in resolutions_data.items() if r.get("meeting_id") != mid}
        del meetings_data[mid]
    _ensure_dir()
    with open(MEETINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(meetings_data, f, indent=2, ensure_ascii=False)
    with open(RESOLUTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(resolutions_data, f, indent=2, ensure_ascii=False)

    del projects[project_id]
    _save_projects(projects)

    # Note: Kùzu doesn't easily cascade-delete; nodes stay until DB reset.
    # For P0 this is acceptable.
    return {"status": "deleted", "id": project_id}
