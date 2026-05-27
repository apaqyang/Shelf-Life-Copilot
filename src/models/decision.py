"""Decision log entry — one persisted record of a director's call on a card.

This is the data source the monthly PDF report aggregates from. v0.1 reads
mock JSON; v0.5 will switch to SQLite without changing this model.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat, field_validator

from src.models.action import ActionType


class DecisionOutcome(StrEnum):
    """What the director did on the alert card.

    REVISED means the director rejected the first suggestion via 改方案 and the
    revised suggestion was ultimately approved — counts as approved for ROI.
    """

    APPROVED = "approved"
    SNOOZED = "snoozed"
    REVISED = "revised"
    REJECTED = "rejected"


class Decision(BaseModel):
    """One persisted decision log entry. Immutable by design."""

    model_config = ConfigDict(frozen=True)

    batch_id: str
    customer_id: str
    material_name: str
    decided_at: datetime
    action: ActionType
    outcome: DecisionOutcome
    savings_estimate: NonNegativeFloat
    actual_savings: NonNegativeFloat | None = None
    actual_qty: NonNegativeFloat | None = None
    notes: str | None = Field(default=None)

    @field_validator("decided_at")
    @classmethod
    def _require_tz(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("decided_at must be timezone-aware")
        return value

    @property
    def is_approved(self) -> bool:
        return self.outcome in (DecisionOutcome.APPROVED, DecisionOutcome.REVISED)
