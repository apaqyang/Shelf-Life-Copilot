"""Tests for the Decision model — one persisted decision log entry."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from src.models import ActionType, Decision, DecisionOutcome


def _base_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "batch_id": "A-001",
        "customer_id": "customerA",
        "material_name": "冷冻虾仁",
        "decided_at": datetime(2026, 5, 26, 7, 15, tzinfo=UTC),
        "action": ActionType.TRANSFORM,
        "outcome": DecisionOutcome.APPROVED,
        "savings_estimate": 8500.0,
        "actual_savings": 8200.0,
        "actual_qty": 830.0,
    }
    payload.update(overrides)
    return payload


class TestDecisionCreation:
    def test_minimal(self) -> None:
        decision = Decision(**_base_payload())
        assert decision.outcome is DecisionOutcome.APPROVED
        assert decision.is_approved is True

    def test_outcome_helpers(self) -> None:
        snoozed = Decision(**_base_payload(outcome=DecisionOutcome.SNOOZED))
        assert snoozed.is_approved is False
        revised = Decision(**_base_payload(outcome=DecisionOutcome.REVISED))
        assert revised.is_approved is True  # revised + ultimately accepted

    def test_actual_savings_optional(self) -> None:
        # Not-yet-executed approvals may have None actual_savings.
        decision = Decision(**_base_payload(actual_savings=None, actual_qty=None))
        assert decision.actual_savings is None


class TestDecisionValidation:
    def test_negative_savings_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Decision(**_base_payload(savings_estimate=-1.0))

    def test_negative_actual_qty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Decision(**_base_payload(actual_qty=-5.0))

    def test_decided_at_must_be_aware(self) -> None:
        # Naive datetime breaks downstream tz math; reject it at the boundary.
        with pytest.raises(ValidationError):
            Decision(**_base_payload(decided_at=datetime(2026, 5, 26, 7, 15)))


class TestDecisionImmutability:
    def test_frozen(self) -> None:
        decision = Decision(**_base_payload())
        with pytest.raises(ValidationError):
            decision.outcome = DecisionOutcome.SNOOZED  # type: ignore[misc]
