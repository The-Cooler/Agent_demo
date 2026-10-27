from typing import Any

from pydantic import BaseModel


class TraceStep(BaseModel):
    step_no: int
    thought: str
    action: str | None = None
    args: dict[str, Any] | None = None
    observation: str | None = None
    status: str
    duration_ms: int = 0


class RunResult(BaseModel):
    run_id: str
    session_id: str
    status: str
    answer: str
    trace: list[TraceStep]
    usage: dict[str, Any] | None = None


class MessageView(BaseModel):
    """返回给前端的消息，assistant 消息附带该轮的 trace。"""

    id: int
    session_id: str
    seq: int
    role: str
    content: str
    meta_json: str | None
    created_at: str
    trace: list[TraceStep] = []
