import json

from app.agent.runtime import AgentRuntime
from app.llm.base import LLMResult
from app.sessions.service import SessionService
from fake_llm import FakeLLM, action, final


def _make_service(repo, registry, settings, script):
    llm = FakeLLM(script)
    runtime = AgentRuntime(repo, llm, registry, settings)
    return SessionService(repo, runtime, settings), llm


async def test_two_sessions_isolated(repo, registry, settings):
    window_one = repo.create_session("窗口 1")
    window_two = repo.create_session("窗口 2")
    service, llm = _make_service(
        repo,
        registry,
        settings,
        [
            final("窗口1开场"),
            action("todo", {"action": "add", "content": "窗口1的待办"}),
            final("窗口1回答"),
            final("窗口2开场"),
            action("todo", {"action": "add", "content": "窗口2的待办"}),
            final("窗口2回答"),
        ],
    )

    await service.send_message(window_one.id, "你好")
    await service.send_message(window_one.id, "记住：窗口一的暗号是 A")
    await service.send_message(window_two.id, "你好")
    await service.send_message(window_two.id, "记住：窗口二的暗号是 B")

    one_messages = repo.list_messages(window_one.id)
    two_messages = repo.list_messages(window_two.id)
    assert [message.content for message in one_messages] == [
        "你好",
        "窗口1开场",
        "记住：窗口一的暗号是 A",
        "窗口1回答",
    ]
    assert [message.content for message in two_messages] == [
        "你好",
        "窗口2开场",
        "记住：窗口二的暗号是 B",
        "窗口2回答",
    ]

    one_todos = repo.list_todos(window_one.id)
    two_todos = repo.list_todos(window_two.id)
    assert [todo.content for todo in one_todos] == ["窗口1的待办"]
    assert [todo.content for todo in two_todos] == ["窗口2的待办"]

    # 再次请求窗口 1，发送给 LLM 的上下文里不能出现窗口 2 的内容
    llm.script = [final("窗口1还是只看到自己")]
    await service.send_message(window_one.id, "我的暗号是什么")
    prompt = json.dumps(llm.received[-1], ensure_ascii=False)
    assert "窗口一的暗号是 A" in prompt
    assert "窗口二的暗号是 B" not in prompt
    assert "窗口2的待办" not in prompt


async def test_summary_isolated_between_sessions(repo, registry, make_settings):
    settings = make_settings(context_max_chars=200, history_keep_messages=2)
    window_one = repo.create_session("窗口 1")
    window_two = repo.create_session("窗口 2")
    service, _ = _make_service(
        repo,
        registry,
        settings,
        [LLMResult(content="窗口 1 的摘要"), final("窗口 1 回答")],
    )
    for index in range(1, 5):
        repo.add_message(window_one.id, "user", f"窗口1消息{index}-" + "内容" * 60)
    repo.add_message(window_two.id, "user", "窗口2只有一条短消息")

    await service.send_message(window_one.id, "继续")

    assert repo.get_session(window_one.id).summary == "窗口 1 的摘要"
    assert repo.get_session(window_two.id).summary == ""
    assert repo.get_session(window_two.id).summary_upto == 0
    two_messages = repo.list_messages(window_two.id)
    assert [message.content for message in two_messages] == ["窗口2只有一条短消息"]


async def test_cross_round_memory(repo, registry, settings):
    session = repo.create_session("跨轮记忆")
    service, llm = _make_service(
        repo,
        registry,
        settings,
        [
            final("你好，我是助手"),
            final("记住了，你的名字是卢俊洋"),
            final("你的名字是卢俊洋"),
        ],
    )

    await service.send_message(session.id, "你好")
    await service.send_message(session.id, "我叫卢俊洋，请记住")
    await service.send_message(session.id, "我叫什么名字？")

    second_context = llm.received[-1]
    contents = [message["content"] for message in second_context]
    assert any("我叫卢俊洋" in content for content in contents)
    assert any("记住了，你的名字是卢俊洋" in content for content in contents)


async def test_follow_up_after_tool_call(repo, registry, settings):
    session = repo.create_session("带工具追问")
    service, llm = _make_service(
        repo,
        registry,
        settings,
        [
            action("calculator", {"expression": "23*17"}),
            final("23*17 的结果是 391"),
            final("再加上 9 是 400"),
        ],
    )

    await service.send_message(session.id, "23*17 是多少")
    await service.send_message(session.id, "再在此基础上加 9 是多少")

    second_context = llm.received[-1]
    joined = "\n".join(message["content"] for message in second_context)
    assert "[工具调用记录]" in joined
    assert "calculator" in joined
    assert "391" in joined
    assert "23*17 的结果是 391" in joined
