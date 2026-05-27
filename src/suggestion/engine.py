"""LLM-backed suggestion generator — provider-agnostic.

SuggestionEngine owns the *business* contract (Pydantic schema, is_standard
decision, error wrapping); LLMProvider owns the *transport* (Anthropic
tool_use vs OpenAI function calling). One engine + many providers.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.models import (
    ActionType,
    Alert,
    Batch,
    CustomerConfig,
    Suggestion,
)
from src.suggestion.prompt import SYSTEM_PROMPT, build_user_prompt
from src.suggestion.providers import LLMProvider, LLMProviderError
from src.suggestion.schema import build_suggestion_tool


class SuggestionEngineError(Exception):
    """Raised when the LLM response cannot be parsed into a Suggestion."""


class _SuggestionPayload(BaseModel):
    """Pydantic-validated view of the LLM tool-call output (vendor-neutral)."""

    action: ActionType
    savings_estimate: float = Field(ge=0.0)
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class SuggestionEngine:
    """Generate disposal suggestions via any LLMProvider that returns tool args."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def suggest(
        self,
        batch: Batch,
        alert: Alert,
        customer: CustomerConfig,
        feedback: str | None = None,
    ) -> Suggestion:
        """Call the LLM and return a validated Suggestion. Raises on malformed response."""
        user_prompt = build_user_prompt(
            batch=batch,
            alert=alert,
            customer=customer,
            feedback=feedback,
        )
        tool = build_suggestion_tool(customer.enabled_actions)

        try:
            raw = await self._provider.call_with_tool(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                tool_schema=tool,
            )
        except LLMProviderError as exc:
            raise SuggestionEngineError(str(exc)) from exc

        payload = _SuggestionPayload.model_validate(raw)

        return Suggestion(
            batch_id=batch.batch_id,
            customer_id=customer.customer_id,
            action=payload.action,
            savings_estimate=payload.savings_estimate,
            rationale=payload.rationale,
            confidence=payload.confidence,
            is_standard=payload.action in customer.enabled_actions,
            llm_model=self._provider.model_name,
            user_feedback=feedback,
        )
