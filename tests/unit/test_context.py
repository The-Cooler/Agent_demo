from app.agent.context import ContextBuilder
from app.llm.base import LLMError, LLMResult
from fake_llm import FakeLLM


def _builder(repo, llm, settings, registry):
    return ContextBuilder(repo, llm, settings, registry)


async def test_context_has_system_and_history(repo, session, registry, settings, fake_llm):
    repo.add_message(session.id, "user", "第一句")
    repo.add_message(session.id, "assistant", "第一句的回答")

    context = await _builder(repo, fake_llm, settings, registry).build(session.id)

    assert context[0]["role"] == "system"
    assert "智能助手" in context[0]["content"]
    # summary_upto=0 时从 seq=0 开始取，首条消息必须进入上下文。
    assert context[1:] == [
        {"role": "user", "content": "第一句"},
        {"role": "assistant", "content": "第一句的回答"},
    ]
    assert len(context) == 3


async def test_context_compresses_and_writes_summary(
    repo, session, registry, make_settings
):
    llm = FakeLLM([LLMResult(content="这是压缩后的会话摘要")])
    settings = make_settings(context_max_chars=200, history_keep_messages=2)
    for index in range(1, 5):
        repo.add_message(session.id, "user", f"消息{index}-" + "内容" * 60)

    context = await _builder(repo, llm, settings, registry).build(session.id)

    stored = repo.get_session(session.id)
    assert stored.summary == "这是压缩后的会话摘要"
    # 消息 seq 从 0 开始，保留最近 2 条后旧批次最后一条的 seq 为 1，故 upto=2。
    assert stored.summary_upto == 2
    assert len(llm.received) == 1
    assert "[会话摘要]" in context[0]["content"]
    assert "这是压缩后的会话摘要" in context[0]["content"]
    # 只保留最近 history_keep_messages 条历史
    assert len(context) == 3
    assert "消息4" in context[-1]["content"]


async def test_context_compression_failure_degrades_gracefully(
    repo, session, registry, make_settings
):
    llm = FakeLLM([LLMError("摘要服务不可用")])
    settings = make_settings(context_max_chars=200, history_keep_messages=2)
    for index in range(1, 5):
        repo.add_message(session.id, "user", f"消息{index}-" + "内容" * 60)

    context = await _builder(repo, llm, settings, registry).build(session.id)

    stored = repo.get_session(session.id)
    assert stored.summary == ""
    assert stored.summary_upto == 0
    assert "[会话摘要]" not in context[0]["content"]
    # 降级为丢弃最旧消息，仅保留最近 history_keep_messages 条
    assert len(context) == 3
    assert "消息4" in context[-1]["content"]
