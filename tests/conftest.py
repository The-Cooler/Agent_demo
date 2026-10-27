import sys
from pathlib import Path

import pytest

# pytest 的 prepend 导入模式只会把测试文件所在目录加入 sys.path，
# 这里显式加入项目根（导入 app）与 tests 目录（导入 fake_llm）。
TESTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = TESTS_DIR.parent
for _path in (ROOT_DIR, TESTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fastapi.testclient import TestClient  # noqa: E402

from app.agent.runtime import AgentRuntime  # noqa: E402
from app.config import Settings  # noqa: E402
from app.sessions.repository import SessionRepository  # noqa: E402
from app.sessions.service import SessionService  # noqa: E402
from app.storage.db import Database  # noqa: E402
from app.tools.base import ToolContext  # noqa: E402
from app.tools.registry import build_registry  # noqa: E402
from fake_llm import FakeLLM  # noqa: E402


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="运行标记为 live 的真实 LLM 测试",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("run_live"):
        return
    skip_live = pytest.mark.skip(reason="live 测试默认跳过，使用 --run-live 运行")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)


@pytest.fixture
def make_settings():
    def _make(**overrides) -> Settings:
        return Settings(_env_file=None, **overrides)

    return _make


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(str(tmp_path / "test.db"))
    database.init_schema()
    return database


@pytest.fixture
def repo(db: Database) -> SessionRepository:
    return SessionRepository(db)


@pytest.fixture
def registry():
    return build_registry()


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def runtime(repo, registry, settings, fake_llm) -> AgentRuntime:
    return AgentRuntime(repo, fake_llm, registry, settings)


@pytest.fixture
def service(repo, runtime, settings) -> SessionService:
    return SessionService(repo, runtime, settings)


@pytest.fixture
def session(repo):
    return repo.create_session("测试会话")


@pytest.fixture
def tool_ctx(session, repo) -> ToolContext:
    return ToolContext(session_id=session.id, repo=repo)


@pytest.fixture
def client(monkeypatch, db, service, registry):
    import app.deps as deps
    from app.main import app

    # deps.py 是模块级单例：把 lifespan 里的 init_db 指向测试数据库，
    # 再用依赖覆盖让路由使用测试 service / registry。
    monkeypatch.setattr(deps, "db", db)
    app.dependency_overrides[deps.get_service] = lambda: service
    app.dependency_overrides[deps.get_registry] = lambda: registry
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
