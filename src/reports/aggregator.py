"""Pure-function aggregator: list[Decision] → MonthlyReportData.

The aggregator owns *what numbers go on the report*; the renderer owns *how
they look*. Keep them separate so the renderer can be replaced (HTML, slides)
without touching business logic.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat, StringConstraints

from src.models import ActionType, Decision

_MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"

# v1.0 annual-fee schedule from PRD §11.2 — used to derive monthly AI cost for ROI.
_TIER_BREAKPOINT_MID = 1_000_000.0
_TIER_BREAKPOINT_HIGH = 3_000_000.0
_TIER_FEE_LOW = 80_000.0
_TIER_FEE_MID = 150_000.0
_TIER_FEE_HIGH = 300_000.0  # placeholder for negotiated > 300 万


def _monthly_subscription_fee(annual_baseline_loss: float) -> float:
    """v1.0 pricing tiers: < 100 万 = ¥80k/yr · 100-300 万 = ¥150k/yr · > 300 万 = 议价."""
    if annual_baseline_loss < _TIER_BREAKPOINT_MID:
        annual = _TIER_FEE_LOW
    elif annual_baseline_loss < _TIER_BREAKPOINT_HIGH:
        annual = _TIER_FEE_MID
    else:
        annual = _TIER_FEE_HIGH
    return annual / 12.0


def _now_utc() -> datetime:
    return datetime.now(UTC)


class ActionTally(BaseModel):
    """One action's monthly performance tally."""

    model_config = ConfigDict(frozen=True)

    action: ActionType
    approved_count: int = Field(ge=0)
    total_actual_savings: NonNegativeFloat


class MonthlyReportData(BaseModel):
    """All the numbers the renderer needs — frozen, serializable, testable."""

    model_config = ConfigDict(frozen=True)

    customer_id: str
    industry: str
    month: Annotated[str, StringConstraints(pattern=_MONTH_PATTERN)]
    total_count: int = Field(ge=0)
    approved_count: int = Field(ge=0)
    approval_rate: float = Field(ge=0.0, le=1.0)
    total_savings_estimate: NonNegativeFloat
    total_savings_actual: NonNegativeFloat
    top_actions: list[ActionTally]
    case_studies: list[Decision]
    annual_baseline_loss: NonNegativeFloat
    monthly_subscription_fee: NonNegativeFloat
    roi_multiple: NonNegativeFloat
    generated_at: datetime = Field(default_factory=_now_utc)


def aggregate_monthly_report(
    *,
    decisions: list[Decision],
    customer_id: str,
    industry: str,
    month: str,
    annual_baseline_loss: float,
) -> MonthlyReportData:
    """Reduce raw decisions to the report data model.

    `decisions` is expected to already be filtered to the target month — the
    aggregator does not re-filter by date (separation of concerns: the loader
    decides what's "in scope", the aggregator just sums).

    `month` must match YYYY-MM; the runtime validator enforces this.
    """
    if not re.match(_MONTH_PATTERN, month):
        raise ValueError(f"month must be YYYY-MM, got {month!r}")

    total_count = len(decisions)
    approved = [d for d in decisions if d.is_approved]
    approved_count = len(approved)
    approval_rate = (approved_count / total_count) if total_count else 0.0

    total_savings_estimate = sum(d.savings_estimate for d in approved)
    total_savings_actual = sum(d.actual_savings or 0.0 for d in approved)

    # Group approved decisions by action; sum actual savings; sort desc; cap at 5.
    by_action: dict[ActionType, list[Decision]] = defaultdict(list)
    for d in approved:
        by_action[d.action].append(d)
    tallies = [
        ActionTally(
            action=action,
            approved_count=len(ds),
            total_actual_savings=sum(d.actual_savings or 0.0 for d in ds),
        )
        for action, ds in by_action.items()
    ]
    top_actions = sorted(tallies, key=lambda t: t.total_actual_savings, reverse=True)[:5]

    # Case studies: top 3 by actual savings, excluding decisions without actual numbers.
    executed = [d for d in approved if d.actual_savings is not None]
    case_studies = sorted(executed, key=lambda d: d.actual_savings or 0.0, reverse=True)[:3]

    monthly_fee = _monthly_subscription_fee(annual_baseline_loss)
    roi_multiple = (total_savings_actual / monthly_fee) if monthly_fee else 0.0

    return MonthlyReportData(
        customer_id=customer_id,
        industry=industry,
        month=month,
        total_count=total_count,
        approved_count=approved_count,
        approval_rate=approval_rate,
        total_savings_estimate=total_savings_estimate,
        total_savings_actual=total_savings_actual,
        top_actions=top_actions,
        case_studies=case_studies,
        annual_baseline_loss=annual_baseline_loss,
        monthly_subscription_fee=monthly_fee,
        roi_multiple=roi_multiple,
    )
