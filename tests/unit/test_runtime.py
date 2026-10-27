import asyncio
import json

import pytest
from pydantic import BaseModel

from app.agent.runtime import AgentRuntime
from app.llm.base import LLMError, LLMResult, ToolCall
from app.tools.base import ToolError
from fake_llm import FakeLLM, action, final


class SlowArgs(BaseModel):
    pass


class SlowTool:
    name = "slow"
    description = "测试超时工具"
    args_model = SlowArgs

    async def run(self, ctx, args):
        await asyncio.sleep(1)
        return "太慢了"


class BrokenArgs(BaseModel):
    pass


class BrokenTool:
    name = "broken"
    description = "测试抛错工具"
    args_model = BrokenArgs

    async def run(self, ctx, args):
        raise ToolError("内部错误")


@pytest.fixture
def make_runtime(repo, registry, settings):
    def _make(script, **overrides):
        llm = FakeLLM(script)
        runtime = AgentRuntime(repo, llm, registry, settings.model_copy(update=overrides))
        return runtime, llm

    return _make


def test_script_element_must_be_llm_result_or_exception():
    # FakeLLM 只能返回 LLMResult 或抛异常；纯字符串不是合法脚本元素。
    assert isinstance(final("x"), LLMResult)
    assert isinstance(action("calculator", {"expression": "1+1"}), LLMResult)


async def test_direct_final_reply(repo, session, make_runtime):
    runtime, llm = make_runtime([final("你好，我是智能助手")])

    result = await runtime.run(session.id, "你好")

    assert result.status == "success"
    assert result.answer == "你好，我是智能助手"
    assert result.trace[-1].status == "final"
    assert len(llm.received) == 1
    messages = repo.list_messages(session.id)
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[-1].content == "你好，我是智能助手"


async def test_tools_passed_to_llm(session, make_runtime):
    runtime, llm = make_runtime([final("好的")])

    await runtime.run(session.id, "你好")

    tools = llm.received_tools[0]
    assert tools is not None
    assert {tool["function"]["name"] for tool in tools} == {
        "calculator",
        "search",
        "weather",
        "todo",
        "read_docs",
    }
    assert all(tool["type"] == "function" for tool in tools)


async def test_single_tool_call(session, make_runtime):
    runtime, _ = make_runtime(
        [
            action("calculator", {"expression": "23*17"}),
            final("23*17 = 391"),
        ]
    )

    result = await runtime.run(session.id, "23*17 等于多少")

    assert result.status == "success"
    assert result.answer == "23*17 = 391"
    # trace 末尾额外有一条 final 步骤：runtime 每个 step_no 都会落表。
    assert [step.action for step in result.trace] == ["calculator", None]
    assert result.trace[0].observation == "391"
    assert result.trace[0].status == "ok"
    assert result.trace[-1].status == "final"


async def test_tool_result_uses_tool_role(session, make_runtime):
    runtime, llm = make_runtime(
        [
            action("calculator", {"expression": "1+1"}),
            final("等于 2"),
        ]
    )

    await runtime.run(session.id, "1+1")

    second_call_messages = llm.received[1]
    roles = [message["role"] for message in second_call_messages]
    assert "tool" in roles
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    assert tool_message["tool_call_id"] == "call_calculator"
    assert tool_message["content"] == "2"
    assistant_with_calls = next(
        m for m in second_call_messages if m["role"] == "assistant" and m.get("tool_calls")
    )
    assert assistant_with_calls["tool_calls"][0]["function"]["name"] == "calculator"


async def test_multi_step_tool_calls(session, make_runtime):
    runtime, _ = make_runtime(
        [
            action("calculator", {"expression": "23*17"}),
            action("calculator", {"expression": "391+9"}),
            final("最终结果是 400"),
        ]
    )

    result = await runtime.run(session.id, "先算 23*17 再加 9")

    assert result.status == "success"
    assert result.answer == "最终结果是 400"
    assert [step.action for step in result.trace] == ["calculator", "calculator", None]
    assert [step.observation for step in result.trace[:2]] == ["391", "400"]


async def test_unknown_tool_becomes_observation_then_succeeds(session, make_runtime):
    runtime, llm = make_runtime(
        [action("nonexistent", {}), final("改用已有信息回答")]
    )

    result = await runtime.run(session.id, "随便调用一个不存在的工具")

    assert result.status == "success"
    assert result.answer == "改用已有信息回答"
    assert result.trace[0].status == "unknown_tool"
    assert "工具不存在：nonexistent" in result.trace[0].observation
    tool_message = next(m for m in llm.received[1] if m["role"] == "tool")
    assert "工具不存在" in tool_message["content"]


async def test_invalid_args_becomes_observation_then_succeeds(session, make_runtime):
    runtime, llm = make_runtime(
        [action("calculator", {"expr": "1+1"}), final("参数确实不合法")]
    )

    result = await runtime.run(session.id, "用错误参数调用计算器")

    assert result.status == "success"
    assert result.trace[0].status == "invalid_args"
    assert "参数校验失败" in result.trace[0].observation
    tool_message = next(m for m in llm.received[1] if m["role"] == "tool")
    assert "参数校验失败" in tool_message["content"]


async def test_invalid_json_arguments_becomes_observation(session, make_runtime):
    runtime, _ = make_runtime(
        [
            LLMResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_bad",
                        name="calculator",
                        arguments={},
                        raw_arguments="{不是合法 JSON",
                        arguments_valid=False,
                    )
                ],
            ),
            final("参数不合法就算了"),
        ]
    )

    result = await runtime.run(session.id, "坏参数")

    assert result.status == "success"
    assert result.trace[0].status == "invalid_args"


async def test_tool_timeout_is_observation(session, registry, make_runtime):
    registry.register(SlowTool())
    runtime, _ = make_runtime(
        [action("slow", {}), final("工具超时了，但我还能回答")],
        tool_timeout_seconds=0.05,
    )

    result = await runtime.run(session.id, "调用慢工具")

    assert result.status == "success"
    assert result.trace[0].status == "timeout"
    assert "执行超时" in result.trace[0].observation


async def test_tool_error_is_observation(session, registry, make_runtime):
    registry.register(BrokenTool())
    runtime, _ = make_runtime([action("broken", {}), final("工具报错后继续回答")])

    result = await runtime.run(session.id, "调用会报错的工具")

    assert result.status == "success"
    assert result.trace[0].status == "error"
    assert "执行失败" in result.trace[0].observation


async def test_exceed_max_react_steps(session, make_runtime):
    runtime, llm = make_runtime(
        [
            action("calculator", {"expression": "1+1"}),
            action("calculator", {"expression": "2+2"}),
            final("强制收尾的最终回答"),
        ],
        max_react_steps=2,
    )

    result = await runtime.run(session.id, "一直调用工具")

    assert result.status == "max_steps"
    assert result.answer == "强制收尾的最终回答"
    assert len(result.trace) == 2
    assert len(llm.received) == 3
    assert "工具调用上限" in llm.received[-1][-1]["content"]
    # 收尾调用不再提供工具，避免模型继续调用。
    assert llm.received_tools[-1] == []


async def test_llm_error_marks_run_error(session, repo, make_runtime):
    runtime, _ = make_runtime([LLMError("模拟上游失败")])

    with pytest.raises(LLMError):
        await runtime.run(session.id, "触发 LLM 异常")

    with repo.db.connect() as conn:
        row = conn.execute("SELECT * FROM runs").fetchone()
    assert row["status"] == "error"
    assert "模拟上游失败" in row["error"]


async def test_final_step_metadata_persisted(session, repo, make_runtime):
    runtime, _ = make_runtime(
        [action("calculator", {"expression": "2*3"}), final("答案是 6")]
    )

    await runtime.run(session.id, "2*3")

    messages = repo.list_messages(session.id)
    assert messages[-1].role == "assistant"
    assert "calculator" in messages[-1].meta_json
