import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.agent.models import MessageView, RunResult, TraceStep
from app.deps import get_service
from app.sessions.service import SessionService

router = APIRouter()


class SendMessageRequest(BaseModel):
    content: str


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str,
    payload: SendMessageRequest,
    service: SessionService = Depends(get_service),
) -> RunResult:
    return await service.send_message(session_id, payload.content)


@router.get("/sessions/{session_id}/messages")
def list_messages(
    session_id: str, service: SessionService = Depends(get_service)
) -> list[MessageView]:
    messages = service.repo.list_messages(session_id)
    traces = service.repo.list_session_traces(session_id)
    run_ids = service.repo.list_session_run_ids(session_id)
    # assistant 消息按出现顺序依次对应一次 run
    views: list[MessageView] = []
    assistant_index = 0
    for message in messages:
        trace: list[TraceStep] = []
        if message.role == "assistant":
            if assistant_index < len(run_ids):
                run_id = run_ids[assistant_index]
                trace = [
                    TraceStep(
                        step_no=step["step_no"],
                        thought=step["thought"] or "",
                        action=step["action"],
                        args=json.loads(step["args_json"]) if step["args_json"] else None,
                        observation=step["observation"],
                        status=step["status"],
                        duration_ms=step["duration_ms"],
                    )
                    for step in traces.get(run_id, [])
                ]
            assistant_index += 1
        views.append(
            MessageView(
                id=message.id,
                session_id=message.session_id,
                seq=message.seq,
                role=message.role,
                content=message.content,
                meta_json=message.meta_json,
                created_at=message.created_at,
                trace=trace,
            )
        )
    return views


@router.get("/sessions/{session_id}/runs/{run_id}")
def get_run(
    session_id: str,
    run_id: str,
    service: SessionService = Depends(get_service),
) -> dict[str, Any]:
    run = service.repo.get_run(run_id)
    if run is None or run["session_id"] != session_id:
        raise HTTPException(status_code=404, detail="run not found")
    return {"run": run, "trace": service.repo.list_trace(run_id)}
