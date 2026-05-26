"""LLM-backed suggestion generator using Claude tool_use for strict JSON output."""

from __future__ import annotations

from typing import Any, cast

from anthropic import AsyncAnthropic
from anthropic.types import Message, MessageParam, ToolChoiceToolParam, ToolParam, ToolUseBlock
from pydantic import BaseModel, Field

from src.models import (
    ActionType,
    Alert,
    Batch,
    CustomerConfig,
    Suggestion,
)
from src.suggestion.prompt import SYSTEM_PROMPT, build_user_prompt
from src.suggestion.schema import TOOL_NAME, build_suggestion_tool

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_AVG_SAVINGS = 5000.0
DEFAULT_MAX_TOKENS = 1024


class SuggestionEngineError(Exception):
    """Raised when the LLM response cannot be parsed into a Suggestion."""


class _ClaudePayload(BaseModel):
    """Pydantic-validated view of the tool_use input returned by Claude."""

    action: ActionType
    savings_estimate: float = Field(ge=0.0)
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class SuggestionEngine:
    """Generate disposal suggestions by calling Claude with strict tool_use output.

    The client is injected so tests can swap in a mocked AsyncAnthropic without
    making real HTTP calls. Production code wires up a real AsyncAnthropic
    instance configured with the project's API key.
    """

    def __init__(
        self,
        client: AsyncAnthropic,
        model: str = DEFAULT_MODEL,
        avg_savings_per_batch: float = DEFAULT_AVG_SAVINGS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._client = client
        self._model = model
        self._avg_savings = avg_savings_per_batch
        self._max_tokens = max_tokens

    async def suggest(
        self,
        batch: Batch,
        alert: Alert,
        customer: CustomerConfig,
        feedback: str | None = None,
    ) -> Suggestion:
        """Call Claude and return a validated Suggestion. Raises on malformed response."""
        user_prompt = build_user_prompt(
            batch=batch,
            alert=alert,
            customer=customer,
            avg_savings_per_batch=self._avg_savings,
            feedback=feedback,
        )
        tool = cast(ToolParam, build_suggestion_tool(customer.enabled_actions))
        messages: list[MessageParam] = [{"role": "user", "content": user_prompt}]
        tool_choice: ToolChoiceToolParam = {"type": "tool", "name": TOOL_NAME}

        message = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=[tool],
            tool_choice=tool_choice,
        )

        payload = self._parse_response(message)

        return Suggestion(
            batch_id=batch.batch_id,
            customer_id=customer.customer_id,
            action=payload.action,
            savings_estimate=payload.savings_estimate,
            rationale=payload.rationale,
            confidence=payload.confidence,
            is_standard=payload.action in customer.enabled_actions,
            llm_model=self._model,
            user_feedback=feedback,
        )

    @staticmethod
    def _parse_response(message: Message) -> _ClaudePayload:
        for block in message.content:
            if isinstance(block, ToolUseBlock) and block.name == TOOL_NAME:
                raw: Any = block.input
                if not isinstance(raw, dict):
                    raise SuggestionEngineError(
                        f"Tool input must be a dict, got {type(raw).__name__}"
                    )
                return _ClaudePayload.model_validate(raw)
        raise SuggestionEngineError(f"Claude response missing tool_use block named {TOOL_NAME!r}")
