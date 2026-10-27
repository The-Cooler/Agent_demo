from typing import Any, Protocol

from pydantic import BaseModel


class LLMUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""
    arguments_valid: bool = True


class LLMResult(BaseModel):
    content: str = ""
    reasoning: str = ""
    tool_calls: list[ToolCall] = []
    usage: LLMUsage | None = None


class LLMError(Exception):
    pass


class LLMClient(Protocol):
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResult:
        ...
