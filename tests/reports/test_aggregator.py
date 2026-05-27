"""Tests for the monthly-report aggregator — pure-function data layer."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.models import ActionType, Decision, DecisionOutcome
from src.reports.aggregator import (
    MonthlyReportData,
    aggregate_monthly_report,
)


def _decision(
    *,
    batch_id: str,
    action: ActionType,
    outcome: DecisionOutcome,
    estimate: float,
    actual: float | None,
    month: int = 5,
    day: int = 10,
    material: str = "冷冻虾仁",
) -> Decision:
    return Decision(
        batch_id=batch_id,
        customer_id="customerA",
        material_name=material,
        decided_at=datetime(2026, month, day, 7, 15, tzinfo=UTC),
        action=action,
        outcome=outcome,
        savings_estimate=estimate,
        actual_savings=actual,
        actual_qty=100.0 if actual is not None else None,
    )


@pytest.fixture
def decisions() -> list[Decision]:
    return [
        _decision(
            batch_id="A-1",
            action=ActionType.TRANSFORM,
            outcome=DecisionOutcome.APPROVED,
            estimate=8500.0,
            actual=8200.0,
            day=2,
        ),
        _decision(
            batch_id="A-2",
            action=ActionType.TRANSFORM,
            outcome=DecisionOutcome.APPROVED,
            estimate=9000.0,
            actual=8800.0,
            day=4,
        ),
        _decision(
            batch_id="A-3",
            action=ActionType.DISCOUNT_CLEARANCE,
            outcome=DecisionOutcome.REVISED,
            estimate=6500.0,
            actual=6300.0,
            day=6,
        ),
        _decision(
            batch_id="A-4",
            action=ActionType.REPORT_LOSS,
            outcome=DecisionOutcome.APPROVED,
            estimate=3200.0,
            actual=3200.0,
            day=8,
        ),
        _decision(
            batch_id="A-5",
            action=ActionType.TRANSFORM,
            outcome=DecisionOutcome.SNOOZED,
            estimate=7000.0,
            actual=None,
            day=10,
        ),
        _decision(
            batch_id="A-6",
            action=ActionType.DISCOUNT_CLEARANCE,
            outcome=DecisionOutcome.REJECTED,
            estimate=5000.0,
            actual=None,
            day=12,
        ),
    ]


class TestAggregateTotals:
    def test_approval_rate_counts_approved_and_revised(self, decisions: list[Decision]) -> None:
        data = aggregate_monthly_report(
            decisions=decisions,
            customer_id="customerA",
            industry="frozen_seafood",
            month="2026-05",
            annual_baseline_loss=1_500_000.0,
        )
        # 6 decisions; APPROVED ×3 + REVISED ×1 = 4 approved; rate = 4/6
        assert data.total_count == 6
        assert data.approved_count == 4
        assert data.approval_rate == pytest.approx(4 / 6)

    def test_total_savings_sum_approved_only(self, decisions: list[Decision]) -> None:
        data = aggregate_monthly_report(
            decisions=decisions,
            customer_id="customerA",
            industry="frozen_seafood",
            month="2026-05",
            annual_baseline_loss=1_500_000.0,
        )
        # 8200 + 8800 + 6300 + 3200 = 26500
        assert data.total_savings_actual == pytest.approx(26500.0)
        # Estimate (approved subset): 8500 + 9000 + 6500 + 3200 = 27200
        assert data.total_savings_estimate == pytest.approx(27200.0)


class TestTopActions:
    def test_actions_ranked_by_actual_savings(self, decisions: list[Decision]) -> None:
        data = aggregate_monthly_report(
            decisions=decisions,
            customer_id="customerA",
            industry="frozen_seafood",
            month="2026-05",
            annual_baseline_loss=1_500_000.0,
        )
        # transform: 8200 + 8800 = 17000  · 2 approved
        # discount_clearance: 6300         · 1 approved
        # report_loss: 3200                · 1 approved
        actions = [(t.action, t.total_actual_savings) for t in data.top_actions]
        assert actions[0] == (ActionType.TRANSFORM, pytest.approx(17000.0))
        assert actions[1] == (ActionType.DISCOUNT_CLEARANCE, pytest.approx(6300.0))
        assert actions[2] == (ActionType.REPORT_LOSS, pytest.approx(3200.0))

    def test_top_actions_capped_at_five(self) -> None:
        many = [
            _decision(
                batch_id=f"X-{i}",
                action=action,
                outcome=DecisionOutcome.APPROVED,
                estimate=1000.0,
                actual=1000.0 - i,  # ensure distinct sort order
                day=(i % 28) + 1,
            )
            for i, action in enumerate(list(ActionType) * 2)  # 10 entries across 5 actions
        ]
        data = aggregate_monthly_report(
            decisions=many,
            customer_id="customerA",
            industry="frozen_seafood",
            month="2026-05",
            annual_baseline_loss=1_500_000.0,
        )
        assert len(data.top_actions) <= 5


class TestCaseStudies:
    def test_three_highest_actual_savings_picked(self, decisions: list[Decision]) -> None:
        data = aggregate_monthly_report(
            decisions=decisions,
            customer_id="customerA",
            industry="frozen_seafood",
            month="2026-05",
            annual_baseline_loss=1_500_000.0,
        )
        assert len(data.case_studies) == 3
        # Sorted desc by actual_savings: 8800, 8200, 6300
        amounts = [c.actual_savings for c in data.case_studies]
        assert amounts == [8800.0, 8200.0, 6300.0]

    def test_skips_decisions_with_no_actual_savings(self) -> None:
        # Only one decision is fully executed; case_studies should have just that one.
        decisions = [
            _decision(
                batch_id="A-1",
                action=ActionType.TRANSFORM,
                outcome=DecisionOutcome.APPROVED,
                estimate=8000.0,
                actual=7800.0,
            ),
            _decision(
                batch_id="A-2",
                action=ActionType.TRANSFORM,
                outcome=DecisionOutcome.SNOOZED,
                estimate=5000.0,
                actual=None,
            ),
        ]
        data = aggregate_monthly_report(
            decisions=decisions,
            customer_id="customerA",
            industry="frozen_seafood",
            month="2026-05",
            annual_baseline_loss=1_500_000.0,
        )
        assert len(data.case_studies) == 1


class TestRoiTiers:
    @pytest.mark.parametrize(
        "annual_loss,expected_monthly_fee",
        [
            (500_000.0, 80_000.0 / 12),  # < 100 万 → 8 万/年
            (1_500_000.0, 150_000.0 / 12),  # 100-300 万 → 15 万/年
            (4_000_000.0, 300_000.0 / 12),  # > 300 万 → 议价，默认 30 万/年
        ],
    )
    def test_monthly_subscription_fee_by_tier(
        self, annual_loss: float, expected_monthly_fee: float
    ) -> None:
        data = aggregate_monthly_report(
            decisions=[],
            customer_id="customerA",
            industry="frozen_seafood",
            month="2026-05",
            annual_baseline_loss=annual_loss,
        )
        assert data.monthly_subscription_fee == pytest.approx(expected_monthly_fee)

    def test_roi_multiple(self) -> None:
        decisions = [
            _decision(
                batch_id="A-1",
                action=ActionType.TRANSFORM,
                outcome=DecisionOutcome.APPROVED,
                estimate=50000.0,
                actual=50000.0,
            )
        ]
        data = aggregate_monthly_report(
            decisions=decisions,
            customer_id="customerA",
            industry="frozen_seafood",
            month="2026-05",
            annual_baseline_loss=1_500_000.0,
        )
        # 50000 saved / (150000/12 ≈ 12500) ≈ 4.0x
        assert data.roi_multiple == pytest.approx(50000.0 / (150_000.0 / 12))

    def test_roi_multiple_zero_when_no_savings(self) -> None:
        data = aggregate_monthly_report(
            decisions=[],
            customer_id="customerA",
            industry="frozen_seafood",
            month="2026-05",
            annual_baseline_loss=1_500_000.0,
        )
        assert data.roi_multiple == 0.0


class TestImmutability:
    def test_report_data_frozen(self) -> None:
        from pydantic import ValidationError

        data = aggregate_monthly_report(
            decisions=[],
            customer_id="customerA",
            industry="frozen_seafood",
            month="2026-05",
            annual_baseline_loss=1_500_000.0,
        )
        with pytest.raises(ValidationError):
            data.customer_id = "customerB"  # type: ignore[misc]


class TestEdgeCases:
    def test_empty_decisions(self) -> None:
        data = aggregate_monthly_report(
            decisions=[],
            customer_id="customerA",
            industry="frozen_seafood",
            month="2026-05",
            annual_baseline_loss=1_500_000.0,
        )
        assert data.total_count == 0
        assert data.approved_count == 0
        assert data.approval_rate == 0.0
        assert data.top_actions == []
        assert data.case_studies == []

    def test_aggregator_rejects_bad_month_format(self) -> None:
        with pytest.raises(ValueError, match="month must be YYYY-MM"):
            aggregate_monthly_report(
                decisions=[],
                customer_id="customerA",
                industry="frozen_seafood",
                month="2026/05",
                annual_baseline_loss=1_500_000.0,
            )

    def test_month_must_be_yyyy_dash_mm(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MonthlyReportData(
                customer_id="customerA",
                industry="frozen_seafood",
                month="May 2026",  # bad format
                total_count=0,
                approved_count=0,
                approval_rate=0.0,
                total_savings_estimate=0.0,
                total_savings_actual=0.0,
                top_actions=[],
                case_studies=[],
                annual_baseline_loss=1_500_000.0,
                monthly_subscription_fee=12500.0,
                roi_multiple=0.0,
            )
