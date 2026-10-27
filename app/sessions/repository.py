import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from app.agent.models import TraceStep
from app.storage.db import Database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Session(BaseModel):
    id: str
    title: str
    status: str
    summary: str
    summary_upto: int
    created_at: str
    updated_at: str


class Message(BaseModel):
    id: int
    session_id: str
    seq: int
    role: str
    content: str
    meta_json: str | None
    created_at: str


class Todo(BaseModel):
    id: int
    session_id: str
    content: str
    status: str
    created_at: str
    completed_at: str | None


class SessionRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ----- sessions -----

    def create_session(self, title: str = "") -> Session:
        session_id = uuid.uuid4().hex
        now = _now()
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, title, status, summary, summary_upto, created_at, updated_at)"
                " VALUES (?, ?, 'idle', '', 0, ?, ?)",
                (session_id, title, now, now),
            )
        return Session(
            id=session_id,
            title=title,
            status="idle",
            summary="",
            summary_upto=0,
            created_at=now,
            updated_at=now,
        )

    def list_sessions(self) -> list[Session]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
        return [Session(**dict(row)) for row in rows]

    def get_session(self, session_id: str) -> Session | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return Session(**dict(row)) if row else None

    def delete_session(self, session_id: str) -> bool:
        with self.db.connect() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cur.rowcount > 0

    def try_start_run(self, session_id: str) -> bool:
        with self.db.connect() as conn:
            cur = conn.execute(
                "UPDATE sessions SET status = 'running', updated_at = ? WHERE id = ? AND status = 'idle'",
                (_now(), session_id),
            )
        return cur.rowcount > 0

    def finish_run_status(self, session_id: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE sessions SET status = 'idle', updated_at = ? WHERE id = ?",
                (_now(), session_id),
            )

    def update_summary(self, session_id: str, summary: str, summary_upto: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE sessions SET summary = ?, summary_upto = ?, updated_at = ? WHERE id = ?",
                (summary, summary_upto, _now(), session_id),
            )

    def set_title(self, session_id: str, title: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                (title, _now(), session_id),
            )

    # ----- messages -----

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        meta: dict[str, Any] | None = None,
    ) -> Message:
        now = _now()
        meta_json = json.dumps(meta, ensure_ascii=False) if meta is not None else None
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), -1) AS max_seq FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            seq = row["max_seq"] + 1
            cur = conn.execute(
                "INSERT INTO messages (session_id, seq, role, content, meta_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, seq, role, content, meta_json, now),
            )
            message_id = cur.lastrowid
            conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        return Message(
            id=message_id,
            session_id=session_id,
            seq=seq,
            role=role,
            content=content,
            meta_json=meta_json,
            created_at=now,
        )

    def list_messages(self, session_id: str, after_seq: int = -1) -> list[Message]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? AND seq > ? ORDER BY seq",
                (session_id, after_seq),
            ).fetchall()
        return [Message(**dict(row)) for row in rows]

    # ----- runs / trace -----

    def create_run(self, session_id: str) -> str:
        run_id = uuid.uuid4().hex
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO runs (id, session_id, status, started_at) VALUES (?, ?, 'running', ?)",
                (run_id, session_id, _now()),
            )
        return run_id

    def finish_run(
        self,
        run_id: str,
        status: str,
        error: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        usage_json = json.dumps(usage, ensure_ascii=False) if usage is not None else None
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE runs SET status = ?, error = ?, usage_json = ?, ended_at = ? WHERE id = ?",
                (status, error, usage_json, _now(), run_id),
            )

    def add_trace_step(self, run_id: str, step: TraceStep) -> None:
        args_json = json.dumps(step.args, ensure_ascii=False) if step.args is not None else None
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO trace_steps (run_id, step_no, thought, action, args_json, observation, status, duration_ms)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    step.step_no,
                    step.thought,
                    step.action,
                    args_json,
                    step.observation,
                    step.status,
                    step.duration_ms,
                ),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_trace(self, run_id: str) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trace_steps WHERE run_id = ? ORDER BY step_no", (run_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def list_session_run_ids(self, session_id: str) -> list[str]:
        """按开始时间返回该会话的 run_id 列表。"""
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM runs WHERE session_id = ? ORDER BY started_at, rowid",
                (session_id,),
            ).fetchall()
        return [row["id"] for row in rows]

    def list_session_traces(self, session_id: str) -> dict[str, list[dict[str, Any]]]:
        """按 run_id 返回该会话所有运行的 trace 步骤。"""
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT t.* FROM trace_steps t"
                " JOIN runs r ON r.id = t.run_id"
                " WHERE r.session_id = ? ORDER BY t.run_id, t.step_no",
                (session_id,),
            ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            item = dict(row)
            run_id = item.pop("run_id")
            grouped.setdefault(run_id, []).append(item)
        return grouped

    # ----- todos -----

    def list_todos(self, session_id: str, status: str | None = None) -> list[Todo]:
        query = "SELECT * FROM todos WHERE session_id = ?"
        params: list[Any] = [session_id]
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY id"
        with self.db.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [Todo(**dict(row)) for row in rows]

    def add_todo(self, session_id: str, content: str) -> Todo:
        now = _now()
        with self.db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO todos (session_id, content, status, created_at) VALUES (?, ?, 'open', ?)",
                (session_id, content, now),
            )
            todo_id = cur.lastrowid
        return Todo(
            id=todo_id,
            session_id=session_id,
            content=content,
            status="open",
            created_at=now,
            completed_at=None,
        )

    def complete_todo(self, session_id: str, todo_id: int) -> bool:
        with self.db.connect() as conn:
            cur = conn.execute(
                "UPDATE todos SET status = 'done', completed_at = ?"
                " WHERE id = ? AND session_id = ? AND status = 'open'",
                (_now(), todo_id, session_id),
            )
        return cur.rowcount > 0

    def delete_todo(self, session_id: str, todo_id: int) -> bool:
        with self.db.connect() as conn:
            cur = conn.execute(
                "DELETE FROM todos WHERE id = ? AND session_id = ?", (todo_id, session_id)
            )
        return cur.rowcount > 0
