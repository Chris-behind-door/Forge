"""
Project Pydantic models for CRUD operations.
"""

from datetime import datetime
from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class Project(BaseModel):
    id: str
    name: str
    description: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class ProjectDetail(Project):
    meeting_count: int = 0
    resolution_count: int = 0
    meetings: list[dict] = Field(default_factory=list)
