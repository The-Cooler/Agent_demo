from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from app.sessions.repository import SessionRepository


@dataclass
class ToolContext:
    session_id: str
    repo: SessionRepository


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    args_model: type[BaseModel]

    async def run(self, ctx: ToolContext, args: BaseModel) -> str:
        ...


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.args_model.model_json_schema(),
            }
            for tool in self._tools.values()
        ]

    def openai_tools(self) -> list[dict[str, Any]]:
        """转成 chat completions 的 tools 参数格式。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.args_model.model_json_schema(),
                },
            }
            for tool in self._tools.values()
        ]


class ToolError(Exception):
    """工具执行失败，异常信息作为 Observation 返回给模型。"""
