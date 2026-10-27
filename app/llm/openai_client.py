import json
from typing import Any

from openai import AsyncOpenAI, OpenAIError

from app.config import Settings
from app.llm.base import LLMError, LLMResult, LLMUsage, ToolCall


class OpenAIClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> AsyncOpenAI:
        # SDK 在 api_key 为空时会于构造时抛 OpenAIError；
        # 延后到首次调用，避免未配置 key 时应用无法启动。
        if self._client is None:
            try:
                self._client = AsyncOpenAI(
                    api_key=self.settings.openai_api_key,
                    base_url=self.settings.openai_base_url,
                    timeout=self.settings.llm_timeout_seconds,
                )
            except OpenAIError as exc:
                raise LLMError(f"初始化 LLM 客户端失败: {exc}") from exc
        return self._client

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResult:
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": self.settings.openai_model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        try:
            response = await client.chat.completions.create(**kwargs)
        except OpenAIError as exc:
            raise LLMError(f"LLM 调用失败: {exc}") from exc

        if not response.choices:
            raise LLMError("LLM 响应中没有 choices")

        message = response.choices[0].message
        tool_calls: list[ToolCall] = []
        for call in message.tool_calls or []:
            raw_arguments = call.function.arguments or ""
            arguments_valid = True
            try:
                arguments = json.loads(raw_arguments) if raw_arguments.strip() else {}
            except json.JSONDecodeError:
                arguments = {}
                arguments_valid = False
            if not isinstance(arguments, dict):
                arguments = {}
                arguments_valid = False
            tool_calls.append(
                ToolCall(
                    id=call.id,
                    name=call.function.name,
                    arguments=arguments,
                    raw_arguments=raw_arguments,
                    arguments_valid=arguments_valid,
                )
            )

        usage: LLMUsage | None = None
        if response.usage is not None:
            usage = LLMUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )
        reasoning = ""
        if message.model_extra:
            reasoning = str(message.model_extra.get("reasoning_content") or "")
        return LLMResult(
            content=message.content or "",
            reasoning=reasoning,
            tool_calls=tool_calls,
            usage=usage,
        )
