from typing import Any

from app.agent.models import RunResult
from app.config import Settings
from app.sessions.errors import SessionBusy, SessionNotFound
from app.sessions.repository import Session, SessionRepository


class SessionService:
    def __init__(self, repo: SessionRepository, runtime: Any, settings: Settings) -> None:
        self.repo = repo
        self.runtime = runtime
        self.settings = settings

    def create(self, title: str = "") -> Session:
        return self.repo.create_session(title)

    def list(self) -> list[Session]:
        return self.repo.list_sessions()

    def get(self, session_id: str) -> Session:
        session = self.repo.get_session(session_id)
        if session is None:
            raise SessionNotFound(session_id)
        return session

    def delete(self, session_id: str) -> None:
        if not self.repo.delete_session(session_id):
            raise SessionNotFound(session_id)

    async def send_message(self, session_id: str, content: str) -> RunResult:
        self.get(session_id)
        if not self.repo.try_start_run(session_id):
            raise SessionBusy(session_id)
        try:
            # user message 由 runtime 保存，service 不重复写入
            result = await self.runtime.run(session_id, content)
        finally:
            self.repo.finish_run_status(session_id)
        self._ensure_title(session_id, content)
        return result

    def _ensure_title(self, session_id: str, content: str) -> None:
        session = self.repo.get_session(session_id)
        if session is None or session.title:
            return
        first_line = content.strip().splitlines()[0] if content.strip() else ""
        title = first_line[:20] + ("…" if len(first_line) > 20 else "")
        if title:
            self.repo.set_title(session_id, title)
