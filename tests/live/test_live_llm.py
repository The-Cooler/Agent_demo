"""真实 LLM 冒烟测试：默认跳过，使用 --run-live 运行。

断言结构性条件（状态、工具名、关键词），不匹配模型原文。
"""

import pytest

from app.agent.runtime import AgentRuntime
from app.config import Settings
from app.llm.openai_client import OpenAIClient
from app.sessions.service import SessionService

pytestmark = pytest.mark.live


@pytest.fixture
def live_settings() -> Settings:
    settings = Settings()
    if not settings.openai_api_key:
        pytest.skip("未配置 OPENAI_API_KEY，跳过 live 测试")
    return settings


@pytest.fixture
def live_llm(live_settings: Settings) -> OpenAIClient:
    return OpenAIClient(live_settings)


@pytest.fixture
def live_service(repo, registry, live_settings, live_llm) -> SessionService:
    runtime = AgentRuntime(repo, live_llm, registry, live_settings)
    return SessionService(repo, runtime, live_settings)


async def test_live_direct_reply(live_service, repo):
    session = repo.create_session("live-direct")

    result = await live_service.send_message(session.id, "你好，请简单介绍一下你自己，不要调用工具。")

    assert result.status == "success"
    assert result.answer.strip()
    assert all(step.action is None for step in result.trace if step.status == "final")


async def test_live_single_calculator_step(live_service, repo):
    session = repo.create_session("live-calculator")

    result = await live_service.send_message(
        session.id, "请使用 calculator 工具计算 23*17，然后把结果告诉我。"
    )

    assert result.status == "success"
    actions = [step.action for step in result.trace if step.action]
    assert "calculator" in actions
    assert "391" in result.answer


async def test_live_multi_step_tools(live_service, repo):
    session = repo.create_session("live-multi")

    result = await live_service.send_message(
        session.id,
        "请使用 calculator 工具：先计算 23*17，然后在这个结果上加 9，最后告诉我最终数值。",
    )

    assert result.status == "success"
    calculator_steps = [step for step in result.trace if step.action == "calculator"]
    assert len(calculator_steps) >= 2
    assert "400" in result.answer


async def test_live_conversational_follow_up(live_service, repo):
    session = repo.create_session("live-memory")

    await live_service.send_message(session.id, "我叫卢俊洋，请记住。不要调用工具。")
    result = await live_service.send_message(session.id, "我叫什么名字？")

    assert result.status == "success"
    assert "卢俊洋" in result.answer


async def test_live_tool_follow_up(live_service, repo):
    session = repo.create_session("live-tool-follow-up")

    first = await live_service.send_message(
        session.id, "请用 calculator 计算 23*17，并告诉我结果。"
    )
    assert first.status == "success"
    assert "391" in first.answer

    second = await live_service.send_message(
        session.id, "在刚才那个计算结果的基础上再加 9，结果是多少？"
    )

    assert second.status == "success"
    assert "400" in second.answer


async def test_live_two_sessions_isolated(live_service, repo):
    window_one = repo.create_session("live-window-1")
    window_two = repo.create_session("live-window-2")

    first = await live_service.send_message(
        window_one.id, "请用 todo 工具新增一条待办：买牛奶。"
    )
    second = await live_service.send_message(
        window_two.id, "请用 todo 工具新增一条待办：买面包。"
    )

    assert first.status == "success"
    assert second.status == "success"
    assert any("买牛奶" in todo.content for todo in repo.list_todos(window_one.id))
    assert any("买面包" in todo.content for todo in repo.list_todos(window_two.id))

    one_contents = [todo.content for todo in repo.list_todos(window_one.id)]
    two_contents = [todo.content for todo in repo.list_todos(window_two.id)]
    assert all("买面包" not in content for content in one_contents)
    assert all("买牛奶" not in content for content in two_contents)
