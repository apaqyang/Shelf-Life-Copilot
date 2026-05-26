"""Alert event raised by the monitoring engine."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from src.models.batch import Severity


def _now_utc() -> datetime:
    return datetime.now(UTC)


class Alert(BaseModel):
    """A near-expiry alert tied to a batch."""

    batch_id: str
    customer_id: str
    triggered_at: datetime = Field(default_factory=_now_utc)
    severity: Severity
    days_left: int
