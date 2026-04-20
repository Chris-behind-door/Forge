"""
Meeting and Resolution Pydantic models.
"""

from datetime import datetime
from pydantic import BaseModel, Field


class MeetingCreate(BaseModel):
    title: str
    date: str
    raw_text: str = ""
    source_doc_id: str | None = None


class MeetingUpdate(BaseModel):
    title: str | None = None
    date: str | None = None
    raw_text: str | None = None
    summary: str | None = None


class Meeting(BaseModel):
    id: str
    project_id: str
    title: str
    date: str
    summary: str = ""
    source_doc_id: str | None = None
    raw_text: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class ResolutionCreate(BaseModel):
    content: str
    index: int
    status: str = "active"
    source_doc_id: str | None = None


class ResolutionUpdate(BaseModel):
    content: str | None = None
    status: str | None = None
    index: int | None = None


class Resolution(BaseModel):
    id: str
    meeting_id: str
    project_id: str
    content: str
    index: int
    status: str = "active"
    source_doc_id: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class RelationCreate(BaseModel):
    from_id: str
    to_id: str
    relation_type: str  # SUPERSEDES | AMENDS | SUPPLEMENTS
    meeting_id: str = ""
    reason: str = ""
    change_summary: str = ""
    supplement_content: str = ""
