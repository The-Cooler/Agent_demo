"""上下文组装与压缩。

返回的列表只包含 system + 历史；当前用户输入由 AgentRuntime 追加，
这样压缩逻辑不必区分“当前输入”和“历史消息”。
"""

import json
import logging

from app.agent.prompt import build_system_prompt
from app.llm.base import LLMClient, LLMError
from app.sessions.repository import Message, SessionRepository
from app.tools.base import ToolRegistry

logger = logging.getLogger(__name__)

SUMMARY_MAX_CHARS = 1500

SUMMARY_PROMPT = (
    "请把下面的对话压缩成不超过 1500 字的摘要，必须保留：用户偏好、已确认的事实、"
    "未完成的事项、上一轮的结论。只输出摘要正文。"
)


def _join_parts(parts: list[str]) -> str:
    return "\n".join(part for part in parts if part)


def _render_history_message(message: Message) -> dict[str, str]:
    content = message.content
    if message.role == "assistant" and message.meta_json:
        try:
            meta = json.loads(message.meta_json)
        except json.JSONDecodeError:
            meta = None
        if isinstance(meta, dict):
            tool_calls = meta.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                lines = ["[工具调用记录]"]
                for call in tool_calls:
                    if not isinstance(call, dict):
                        continue
                    lines.append(
                        "调用 {name}，参数 {args}，观测 {observation}".format(
                            name=call.get("name", ""),
                            args=json.dumps(call.get("args"), ensure_ascii=False),
                            observation=call.get("observation", ""),
                        )
                    )
                content = (content + "\n\n" + "\n".join(lines)).strip()
    return {"role": message.role, "content": content}


class ContextBuilder:
    def __init__(
        self,
        repo: SessionRepository,
        llm: LLMClient,
        settings,
        registry: ToolRegistry,
    ) -> None:
        self.repo = repo
        self.llm = llm
        self.settings = settings
        self.registry = registry

    async def build(self, session_id: str) -> list[dict[str, str]]:
        session = self.repo.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")

        summary = session.summary
        messages = self.repo.list_messages(session_id, after_seq=session.summary_upto - 1)

        total_chars = len(summary) + sum(len(message.content) for message in messages)
        if total_chars > self.settings.context_max_chars * 0.8:
            summary, messages = await self._compress(session_id, summary, messages)

        todos = [
            todo.model_dump()
            for todo in self.repo.list_todos(session_id, status="open")
        ]
        system_prompt = build_system_prompt(todos)

        system_parts = [system_prompt]
        if summary:
            system_parts.append(f"[会话摘要]\n{summary}")

        context: list[dict[str, str]] = [
            {"role": "system", "content": _join_parts(system_parts)}
        ]
        context.extend(_render_history_message(message) for message in messages)
        return context

    async def _compress(
        self,
        session_id: str,
        summary: str,
        messages: list[Message],
    ) -> tuple[str, list[Message]]:
        cut = max(len(messages) - self.settings.history_keep_messages, 0)
        if cut == 0:
            return summary, messages
        old_messages = messages[:cut]
        recent_messages = messages[cut:]
        new_upto = old_messages[-1].seq + 1

        prompt = _join_parts(
            [summary] + [f"{message.role}: {message.content}" for message in old_messages]
        )
        try:
            result = await self.llm.complete(
                [
                    {"role": "system", "content": SUMMARY_PROMPT},
                    {"role": "user", "content": prompt},
                ]
            )
        except LLMError as exc:
            logger.warning(
                "context compression failed for session %s: %s", session_id, exc
            )
            return summary, recent_messages
        except Exception as exc:
            logger.warning(
                "context compression failed unexpectedly for session %s: %s",
                session_id,
                exc,
            )
            return summary, recent_messages

        new_summary = result.content.strip()[:SUMMARY_MAX_CHARS]
        self.repo.update_summary(session_id, new_summary, summary_upto=new_upto)
        return new_summary, recent_messages
