"""ReAct 主循环。

不管理 session 的 running/idle 状态，那由 SessionService 负责。
工具调用使用 chat completions 的原生 tool_calls，不再让模型输出 JSON 协议。
"""

import asyncio
import json
import logging
import time
from typing import Any

from pydantic import ValidationError

from app.agent.context import ContextBuilder
from app.agent.models import RunResult, TraceStep
from app.llm.base import LLMClient, LLMUsage, ToolCall
from app.sessions.repository import SessionRepository
from app.tools.base import ToolContext, ToolError, ToolRegistry

logger = logging.getLogger(__name__)

MAX_STEPS_PROMPT = (
    "已达到本次运行的工具调用上限。请不要再调用工具，"
    "根据已有信息直接用中文给出最终回答。"
)


def _add_usage(total: LLMUsage, usage: LLMUsage | None) -> None:
    if usage is None:
        return
    total.prompt_tokens += usage.prompt_tokens
    total.completion_tokens += usage.completion_tokens
    total.total_tokens += usage.total_tokens


class AgentRuntime:
    def __init__(
        self,
        repo: SessionRepository,
        llm: LLMClient,
        registry: ToolRegistry,
        settings,
        context_builder: ContextBuilder | None = None,
    ) -> None:
        self.repo = repo
        self.llm = llm
        self.registry = registry
        self.settings = settings
        self.context_builder = context_builder or ContextBuilder(
            repo, llm, settings, registry
        )

    async def run(self, session_id: str, user_input: str) -> RunResult:
        self.repo.add_message(session_id, "user", user_input)
        run_id = self.repo.create_run(session_id)
        usage = LLMUsage()
        trace: list[TraceStep] = []
        tool_calls_log: list[dict[str, Any]] = []
        try:
            context = await self.context_builder.build(session_id)
            scratchpad: list[dict[str, Any]] = []
            tools = self.registry.openai_tools()

            for step_no in range(1, self.settings.max_react_steps + 1):
                result = await self.llm.complete(context + scratchpad, tools=tools)
                _add_usage(usage, result.usage)

                if not result.tool_calls:
                    answer = result.content.strip()
                    trace_step = TraceStep(
                        step_no=step_no,
                        thought=result.reasoning,
                        observation=answer,
                        status="final",
                    )
                    self.repo.add_trace_step(run_id, trace_step)
                    trace.append(trace_step)
                    meta = {"tool_calls": tool_calls_log} if tool_calls_log else None
                    self.repo.add_message(session_id, "assistant", answer, meta=meta)
                    self.repo.finish_run(
                        run_id, status="success", usage=usage.model_dump()
                    )
                    return RunResult(
                        run_id=run_id,
                        session_id=session_id,
                        status="success",
                        answer=answer,
                        trace=trace,
                        usage=usage.model_dump(),
                    )

                scratchpad.append(
                    {
                        "role": "assistant",
                        "content": result.content or "",
                        "tool_calls": [
                            {
                                "id": call.id,
                                "type": "function",
                                "function": {
                                    "name": call.name,
                                    "arguments": call.raw_arguments or json.dumps(call.arguments),
                                },
                            }
                            for call in result.tool_calls
                        ],
                    }
                )

                for call in result.tool_calls:
                    started = time.monotonic()
                    observation, status = await self._execute_tool(session_id, call)
                    duration_ms = int((time.monotonic() - started) * 1000)
                    trace_step = TraceStep(
                        step_no=step_no,
                        thought=result.reasoning,
                        action=call.name,
                        args=call.arguments,
                        observation=observation,
                        status=status,
                        duration_ms=duration_ms,
                    )
                    self.repo.add_trace_step(run_id, trace_step)
                    trace.append(trace_step)
                    if status == "ok":
                        tool_calls_log.append(
                            {
                                "name": call.name,
                                "args": call.arguments,
                                "observation": observation,
                            }
                        )
                    scratchpad.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": observation,
                        }
                    )

            forced = await self.llm.complete(
                context + scratchpad + [{"role": "user", "content": MAX_STEPS_PROMPT}],
                tools=[],
            )
            _add_usage(usage, forced.usage)
            answer = forced.content.strip()
            meta = {"tool_calls": tool_calls_log} if tool_calls_log else None
            self.repo.add_message(session_id, "assistant", answer, meta=meta)
            self.repo.finish_run(run_id, status="max_steps", usage=usage.model_dump())
            return RunResult(
                run_id=run_id,
                session_id=session_id,
                status="max_steps",
                answer=answer,
                trace=trace,
                usage=usage.model_dump(),
            )
        except Exception as exc:
            logger.warning("agent run failed run_id=%s session_id=%s", run_id, session_id)
            self.repo.finish_run(
                run_id, status="error", error=str(exc), usage=usage.model_dump()
            )
            raise

    async def _execute_tool(
        self, session_id: str, call: ToolCall
    ) -> tuple[str, str]:
        """返回 (observation, trace_status)，任何失败都转成观测文本而不中断循环。"""
        tool = self.registry.get(call.name)
        if tool is None:
            return (
                f"工具不存在：{call.name}。可用工具：{', '.join(self.registry.names())}",
                "unknown_tool",
            )
        if not call.arguments_valid:
            return f"工具 {call.name} 的参数不是合法 JSON 对象：{call.raw_arguments}", "invalid_args"
        try:
            args = tool.args_model.model_validate(call.arguments)
        except ValidationError as exc:
            return f"参数校验失败：{exc}", "invalid_args"

        ctx = ToolContext(session_id=session_id, repo=self.repo)
        try:
            observation = await asyncio.wait_for(
                tool.run(ctx, args), timeout=self.settings.tool_timeout_seconds
            )
        except asyncio.TimeoutError:
            return (
                f"工具 {tool.name} 执行超时（超过 {self.settings.tool_timeout_seconds} 秒）",
                "timeout",
            )
        except ToolError as exc:
            return f"工具 {tool.name} 执行失败：{exc}", "error"
        except Exception as exc:
            return f"工具 {tool.name} 执行异常：{exc}", "error"
        return observation, "ok"
