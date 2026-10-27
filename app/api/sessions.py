from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.deps import get_service
from app.sessions.repository import Session
from app.sessions.service import SessionService

router = APIRouter()


class CreateSessionRequest(BaseModel):
    title: str = ""


@router.post("/sessions")
def create_session(
    payload: CreateSessionRequest,
    service: SessionService = Depends(get_service),
) -> Session:
    return service.create(payload.title)


@router.get("/sessions")
def list_sessions(service: SessionService = Depends(get_service)) -> list[Session]:
    return service.list()


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str, service: SessionService = Depends(get_service)
) -> Session:
    return service.get(session_id)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: str, service: SessionService = Depends(get_service)
) -> None:
    service.delete(session_id)
