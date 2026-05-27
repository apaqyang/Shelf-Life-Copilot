"""LLM provider abstraction — decouple SuggestionEngine from any single vendor.

v0.1 ships two providers:
- AnthropicProvider: Claude tool_use (the original v0.1 path)
- MoonshotProvider:  Moonshot / KIMI via OpenAI-compatible function calling

Both providers normalize the model's tool-call output to a plain dict that
SuggestionEngine then validates into a Suggestion. This is the only seam
LLM vendor-specifics are allowed to leak through.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, cast, runtime_checkable

from anthropic import AsyncAnthropic
from anthropic.types import (
    Message,
    MessageParam,
    ToolChoiceToolParam,
    ToolParam,
    ToolUseBlock,
)
from openai import AsyncOpenAI

from src.suggestion.schema import TOOL_NAME

ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-6"
MOONSHOT_DEFAULT_MODEL = "moonshot-v1-32k"
MOONSHOT_BASE_URL = "https://api.moonshot.cn/v1"
DEFAULT_MAX_TOKENS = 1024


class LLMProviderError(Exception):
    """Raised when a provider can't return a valid tool-call payload."""


@runtime_checkable
class LLMProvider(Protocol):
    """Calls an LLM with a forced tool/function call and returns parsed args."""

    @property
    def model_name(self) -> str: ...  # pragma: no cover

    async def call_with_tool(
        self,
        system_prompt: str,
        user_prompt: str,
        tool_schema: dict[str, Any],
    ) -> dict[str, Any]: ...  # pragma: no cover


class AnthropicProvider:
    """Calls Claude with `tool_use` forced to the named tool — strict JSON via schema."""

    def __init__(
        self,
        client: AsyncAnthropic,
        model: str = ANTHROPIC_DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens

    @property
    def model_name(self) -> str:
        return self._model

    async def call_with_tool(
        self,
        system_prompt: str,
        user_prompt: str,
        tool_schema: dict[str, Any],
    ) -> dict[str, Any]:
        tool = cast(ToolParam, tool_schema)
        messages: list[MessageParam] = [{"role": "user", "content": user_prompt}]
        tool_choice: ToolChoiceToolParam = {"type": "tool", "name": TOOL_NAME}

        message = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system_prompt,
            messages=messages,
            tools=[tool],
            tool_choice=tool_choice,
        )
        return self._extract(message)

    @staticmethod
    def _extract(message: Message) -> dict[str, Any]:
        for block in message.content:
            if isinstance(block, ToolUseBlock) and block.name == TOOL_NAME:
                raw: Any = block.input
                if not isinstance(raw, dict):
                    raise LLMProviderError(f"Tool input must be a dict, got {type(raw).__name__}")
                return raw
        raise LLMProviderError(f"Claude response missing tool_use block named {TOOL_NAME!r}")


class MoonshotProvider:
    """Calls Moonshot/KIMI through its OpenAI-compatible chat-completions endpoint.

    Translates Claude's tool_use schema (`{name, input_schema, ...}`) to OpenAI's
    function spec (`{type: function, function: {name, parameters, ...}}`). The
    JSON schema body is identical between vendors, only the wrapper differs.
    """

    def __init__(
        self,
        client: AsyncOpenAI,
        model: str = MOONSHOT_DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens

    @property
    def model_name(self) -> str:
        return self._model

    async def call_with_tool(
        self,
        system_prompt: str,
        user_prompt: str,
        tool_schema: dict[str, Any],
    ) -> dict[str, Any]:
        function_spec = {
            "type": "function",
            "function": {
                "name": tool_schema["name"],
                "description": tool_schema.get("description", ""),
                "parameters": tool_schema["input_schema"],
            },
        }
        # OpenAI SDK 的 model 字段被严格 Literal 到 GPT-* 名称——Moonshot 用同协议
        # 但是不同模型名，所以这里把 kwargs 走 cast(Any) 绕过类型限制。
        completion = await self._client.chat.completions.create(
            model=cast(Any, self._model),
            max_tokens=self._max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            tools=[cast(Any, function_spec)],
            tool_choice=cast(Any, {"type": "function", "function": {"name": tool_schema["name"]}}),
        )
        return self._extract(completion)

    @staticmethod
    def _extract(completion: Any) -> dict[str, Any]:
        choices = completion.choices
        if not choices:
            raise LLMProviderError("Moonshot response had no choices")
        message = choices[0].message
        tool_calls = message.tool_calls or []
        if not tool_calls:
            raise LLMProviderError("Moonshot response missing tool_calls")
        first = tool_calls[0]
        raw_args = first.function.arguments
        try:
            args: Any = json.loads(raw_args)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(f"Moonshot tool arguments not valid JSON: {exc}") from exc
        if not isinstance(args, dict):
            raise LLMProviderError(
                f"Moonshot tool arguments must decode to a dict, got {type(args).__name__}"
            )
        return args


def build_anthropic_provider(
    api_key: str, model: str = ANTHROPIC_DEFAULT_MODEL
) -> AnthropicProvider:
    return AnthropicProvider(client=AsyncAnthropic(api_key=api_key), model=model)


def build_moonshot_provider(api_key: str, model: str = MOONSHOT_DEFAULT_MODEL) -> MoonshotProvider:
    return MoonshotProvider(
        client=AsyncOpenAI(api_key=api_key, base_url=MOONSHOT_BASE_URL),
        model=model,
    )
