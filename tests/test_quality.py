from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.models import ActionType, Decision, DecisionOutcome, Suggestion
from src.quality import build_outcome_quality_report


def _decision(
    batch_id: str,
    *,
    estimate: float = 100,
    actual: float | None = 90,
    customer_id: str = "tenant",
) -> Decision:
    return Decision(
        batch_id=batch_id,
        customer_id=customer_id,
        material_name="food",
        decided_at=datetime(2026, 1, 1, tzinfo=UTC),
        action=ActionType.TRANSFORM,
        outcome=DecisionOutcome.APPROVED,
        savings_estimate=estimate,
        actual_savings=actual,
    )


def _suggestion(batch_id: str, provider: str = "provider-a") -> Suggestion:
    return Suggestion(
        batch_id=batch_id,
        customer_id="tenant",
        action=ActionType.TRANSFORM,
        savings_estimate=100,
        rationale="test",
        confidence=0.9,
        is_standard=True,
        llm_model=provider,
    )


def test_verified_outcomes_are_grouped_by_provider_and_action() -> None:
    suggestions = {batch: _suggestion(batch) for batch in ("a", "b")}
    report = build_outcome_quality_report(
        customer_id="tenant",
        decisions=[
            _decision("a", estimate=100, actual=80),
            _decision("b", estimate=60, actual=60),
            _decision("unverified", actual=None),
            _decision("other", customer_id="other"),
        ],
        suggestion_for_batch=lambda _customer, batch, _at: suggestions.get(batch),
        min_verified_samples=2,
        max_normalized_error=0.2,
    )
    assert report.gate_passed
    assert report.verified_count == 2
    segment = report.segments[0]
    assert segment.sample_count == 2
    assert segment.mean_estimated_savings == 80
    assert segment.mean_actual_savings == 70
    assert segment.mean_bias == 10
    assert segment.mean_absolute_error == 10


def test_quality_gate_reports_missing_matches_samples_and_excess_error() -> None:
    report = build_outcome_quality_report(
        customer_id="tenant",
        decisions=[_decision("matched", estimate=100, actual=0), _decision("missing")],
        suggestion_for_batch=lambda _customer, batch, _at: (
            _suggestion(batch, "provider-b") if batch == "matched" else None
        ),
        min_verified_samples=3,
        max_normalized_error=0.5,
    )
    assert not report.gate_passed
    assert report.unmatched_count == 1
    assert report.segments[0].normalized_absolute_error == 100
    assert "below minimum" in report.gate_reasons[0]
    assert "provider-b/transform" in report.gate_reasons[1]


@pytest.mark.parametrize(
    ("minimum", "threshold"),
    [(0, 0.5), (1, -1)],
)
def test_quality_gate_configuration_is_validated(minimum: int, threshold: float) -> None:
    with pytest.raises(ValueError, match="invalid quality"):
        build_outcome_quality_report(
            customer_id="tenant",
            decisions=[],
            suggestion_for_batch=lambda _customer, _batch, _at: None,
            min_verified_samples=minimum,
            max_normalized_error=threshold,
        )
