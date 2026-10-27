from app.agent.runtime import AgentRuntime
from app.config import Settings
from app.llm.openai_client import OpenAIClient
from app.sessions.repository import SessionRepository
from app.sessions.service import SessionService
from app.storage.db import Database
from app.tools.base import ToolRegistry
from app.tools.registry import build_registry

settings = Settings()
db = Database(settings.db_path)
repo = SessionRepository(db)
registry: ToolRegistry = build_registry()
llm = OpenAIClient(settings)
runtime = AgentRuntime(repo, llm, registry, settings)
service = SessionService(repo, runtime, settings)


def init_db() -> None:
    db.init_schema()


def get_service() -> SessionService:
    return service


def get_registry() -> ToolRegistry:
    return registry
