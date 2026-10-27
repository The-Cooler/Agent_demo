"""仅测试使用：FakeLLM 是 LLMClient 协议的测试替身，不进入生产运行路径。"""

import json
from typing import Any

from app.llm.base import LLMError, LLMResult, ToolCall


class FakeLLM:
    """按脚本依次返回 LLMResult；脚本元素也可以是异常实例，用于模拟 LLMError。

    received 保存每次 complete 收到的 messages 快照，便于断言上下文内容。
    """

    def __init__(self, script: list[Any] | None = None) -> None:
        self.script: list[Any] = list(script or [])
        self.received: list[list[dict[str, Any]]] = []
        self.received_tools: list[list[dict[str, Any]] | None] = []

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResult:
        self.received.append([dict(message) for message in messages])
        self.received_tools.append(tools)
        if not self.script:
            raise LLMError("FakeLLM 脚本已耗尽")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def action(
    name: str,
    arguments: dict[str, Any] | None = None,
    thought: str = "需要调用工具",
) -> LLMResult:
    call = ToolCall(
        id=f"call_{name}",
        name=name,
        arguments=arguments or {},
        raw_arguments=json.dumps(arguments or {}, ensure_ascii=False),
    )
    return LLMResult(content=thought, tool_calls=[call])


def final(answer: str, thought: str = "") -> LLMResult:
    return LLMResult(content=answer)
