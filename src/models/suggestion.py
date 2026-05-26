"""Suggestion model — LLM-generated disposal recommendation for one batch."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from src.models.action import ActionType


def _now_utc() -> datetime:
    return datetime.now(UTC)


class Suggestion(BaseModel):
    """One disposal recommendation produced by the LLM for a single batch.

    `is_standard` is False when the chosen action is not in the customer's
    enabled_actions list — meaning the suggestion came from a "改方案" feedback
    that crossed the standard boundary and must be flagged for human review.
    """

    model_config = ConfigDict(frozen=True)

    batch_id: str
    customer_id: str
    action: ActionType
    savings_estimate: float = Field(ge=0.0)
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    is_standard: bool
    generated_at: datetime = Field(default_factory=_now_utc)
    llm_model: str = Field(min_length=1)
    user_feedback: str | None = None
