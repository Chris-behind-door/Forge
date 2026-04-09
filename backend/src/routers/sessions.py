"""Session CRUD API router."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..models.session import (
    create_session,
    delete_session,
    get_session,
    list_sessions,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    title: str = Field(default="新对话", description="会话标题")


@router.get("")
async def api_list_sessions():
    return list_sessions()


@router.post("")
async def api_create_session(req: CreateSessionRequest | None = None):
    title = req.title if req else "新对话"
    return create_session(title=title)


@router.get("/{session_id}")
async def api_get_session(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.delete("/{session_id}")
async def api_delete_session(session_id: str):
    if not delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}
