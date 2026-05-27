"""Tests for the LLM provider abstraction.

We mock the underlying SDK clients (AsyncAnthropic / AsyncOpenAI) and verify
each provider correctly translates the call shape and extracts a dict payload.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from anthropic import AsyncAnthropic
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage
from openai import AsyncOpenAI

from src.suggestion.providers import (
    AnthropicProvider,
    LLMProviderError,
    MoonshotProvider,
    build_anthropic_provider,
    build_moonshot_provider,
)
from src.suggestion.schema import TOOL_NAME

_TOOL_SCHEMA: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": "test tool",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["transform"]},
            "savings_estimate": {"type": "number"},
            "rationale": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": ["action", "savings_estimate", "rationale", "confidence"],
    },
}


def _anthropic_msg(content: list[Any]) -> Message:
    return Message(
        id="msg_test",
        model="claude-sonnet-4-6",
        role="assistant",
        type="message",
        content=content,
        stop_reason="tool_use",
        stop_sequence=None,
        usage=Usage(input_tokens=10, output_tokens=20),
    )


def _tool_use_block(payload: dict[str, Any]) -> ToolUseBlock:
    return ToolUseBlock(id="tu_1", input=payload, name=TOOL_NAME, type="tool_use")


def _text_block(text: str) -> TextBlock:
    return TextBlock(text=text, type="text", citations=None)


class TestAnthropicProvider:
    async def test_extracts_tool_use_dict(self) -> None:
        client = MagicMock(spec=AsyncAnthropic)
        client.messages = MagicMock()
        client.messages.create = AsyncMock(
            return_value=_anthropic_msg(
                [
                    _tool_use_block(
                        {
                            "action": "transform",
                            "savings_estimate": 8500.0,
                            "rationale": "历史采纳率高",
                            "confidence": 0.85,
                        }
                    )
                ]
            )
        )
        provider = AnthropicProvider(client=client, model="claude-sonnet-4-6")
        out = await provider.call_with_tool("sys", "user", _TOOL_SCHEMA)
        assert out["action"] == "transform"
        assert provider.model_name == "claude-sonnet-4-6"
        # Verify call shape: tool_choice forced to the named tool.
        kwargs = client.messages.create.await_args.kwargs
        assert kwargs["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
        assert kwargs["model"] == "claude-sonnet-4-6"

    async def test_raises_when_no_tool_use_block(self) -> None:
        client = MagicMock(spec=AsyncAnthropic)
        client.messages = MagicMock()
        client.messages.create = AsyncMock(
            return_value=_anthropic_msg([_text_block("沒走到 tool_use")])
        )
        provider = AnthropicProvider(client=client)
        with pytest.raises(LLMProviderError, match="missing tool_use"):
            await provider.call_with_tool("sys", "user", _TOOL_SCHEMA)

    async def test_raises_when_tool_input_is_not_dict(self) -> None:
        # Use model_construct() to bypass pydantic validation and create a
        # ToolUseBlock whose .input is a string — only way to exercise the
        # defensive dict-check branch in real production code.
        bad_block = ToolUseBlock.model_construct(
            id="tu_2", input="not a dict", name=TOOL_NAME, type="tool_use"
        )
        client = MagicMock(spec=AsyncAnthropic)
        client.messages = MagicMock()
        client.messages.create = AsyncMock(return_value=_anthropic_msg([bad_block]))
        provider = AnthropicProvider(client=client)
        with pytest.raises(LLMProviderError, match="must be a dict"):
            await provider.call_with_tool("sys", "user", _TOOL_SCHEMA)

    def test_factory(self) -> None:
        provider = build_anthropic_provider("sk-test", model="claude-opus-4-7")
        assert provider.model_name == "claude-opus-4-7"


# ---------------------------------------------------------------------------
# Moonshot
# ---------------------------------------------------------------------------


def _moonshot_completion(arguments: str, name: str = TOOL_NAME) -> Any:
    """Build an OpenAI-style ChatCompletion mock with one tool_call."""
    tool_call = MagicMock()
    tool_call.function = MagicMock()
    tool_call.function.name = name
    tool_call.function.arguments = arguments
    message = MagicMock()
    message.tool_calls = [tool_call]
    choice = MagicMock()
    choice.message = message
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def _moonshot_completion_no_tools() -> Any:
    message = MagicMock()
    message.tool_calls = None
    choice = MagicMock()
    choice.message = message
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def _moonshot_completion_no_choices() -> Any:
    completion = MagicMock()
    completion.choices = []
    return completion


class TestMoonshotProvider:
    async def test_translates_schema_and_extracts_args(self) -> None:
        client = MagicMock(spec=AsyncOpenAI)
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(
            return_value=_moonshot_completion(
                json.dumps(
                    {
                        "action": "transform",
                        "savings_estimate": 8500.0,
                        "rationale": "历史采纳率高",
                        "confidence": 0.85,
                    }
                )
            )
        )
        provider = MoonshotProvider(client=client, model="moonshot-v1-32k")
        out = await provider.call_with_tool("sys", "user", _TOOL_SCHEMA)
        assert out["action"] == "transform"
        kwargs = client.chat.completions.create.await_args.kwargs
        # Tool spec must be the OpenAI function shape, not the Anthropic one.
        assert kwargs["tools"][0]["type"] == "function"
        assert kwargs["tools"][0]["function"]["name"] == TOOL_NAME
        assert kwargs["tools"][0]["function"]["parameters"] == _TOOL_SCHEMA["input_schema"]
        # tool_choice forces the named function.
        assert kwargs["tool_choice"] == {
            "type": "function",
            "function": {"name": TOOL_NAME},
        }

    async def test_raises_when_no_choices(self) -> None:
        client = MagicMock(spec=AsyncOpenAI)
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=_moonshot_completion_no_choices())
        provider = MoonshotProvider(client=client)
        with pytest.raises(LLMProviderError, match="no choices"):
            await provider.call_with_tool("sys", "user", _TOOL_SCHEMA)

    async def test_raises_when_no_tool_calls(self) -> None:
        client = MagicMock(spec=AsyncOpenAI)
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=_moonshot_completion_no_tools())
        provider = MoonshotProvider(client=client)
        with pytest.raises(LLMProviderError, match="missing tool_calls"):
            await provider.call_with_tool("sys", "user", _TOOL_SCHEMA)

    async def test_raises_on_invalid_json_arguments(self) -> None:
        client = MagicMock(spec=AsyncOpenAI)
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(
            return_value=_moonshot_completion("{not-valid-json")
        )
        provider = MoonshotProvider(client=client)
        with pytest.raises(LLMProviderError, match="not valid JSON"):
            await provider.call_with_tool("sys", "user", _TOOL_SCHEMA)

    async def test_raises_when_arguments_decode_to_non_dict(self) -> None:
        client = MagicMock(spec=AsyncOpenAI)
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(
            return_value=_moonshot_completion(json.dumps(["a", "b"]))
        )
        provider = MoonshotProvider(client=client)
        with pytest.raises(LLMProviderError, match="must decode to a dict"):
            await provider.call_with_tool("sys", "user", _TOOL_SCHEMA)

    def test_factory(self) -> None:
        provider = build_moonshot_provider("sk-test", model="kimi-latest")
        assert provider.model_name == "kimi-latest"
