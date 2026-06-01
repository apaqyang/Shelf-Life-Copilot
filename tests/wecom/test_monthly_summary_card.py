"""Monthly summary card renderer — markdown sent alongside the PDF push."""

from __future__ import annotations

from datetime import UTC, datetime

from src.models import ActionType
from src.models.card import CardKind
from src.reports.aggregator import ActionTally, MonthlyReportData
from src.wecom.cards import render_monthly_summary_card


def _sample_data(
    *,
    customer_id: str = "customerA",
    industry: str = "frozen_seafood",
    month: str = "2026-05",
    total_count: int = 15,
    approved_count: int = 14,
    total_savings_estimate: float = 90000.0,
    total_savings_actual: float = 82700.0,
    roi_multiple: float = 6.6,
) -> MonthlyReportData:
    return MonthlyReportData(
        customer_id=customer_id,
        industry=industry,
        month=month,
        total_count=total_count,
        approved_count=approved_count,
        approval_rate=approved_count / total_count if total_count else 0.0,
        total_savings_estimate=total_savings_estimate,
        total_savings_actual=total_savings_actual,
        top_actions=[
            ActionTally(
                action=ActionType.TRANSFORM,
                approved_count=8,
                total_actual_savings=38400.0,
            ),
            ActionTally(
                action=ActionType.DISCOUNT_CLEARANCE,
                approved_count=5,
                total_actual_savings=28300.0,
            ),
        ],
        case_studies=[],
        annual_baseline_loss=1_500_000.0,
        monthly_subscription_fee=12500.0,
        roi_multiple=roi_multiple,
        generated_at=datetime(2026, 6, 1, 0, 1, tzinfo=UTC),
    )


class TestRenderMonthlySummaryCard:
    def test_kind_is_monthly_summary(self) -> None:
        card = render_monthly_summary_card(_sample_data())
        assert card.kind is CardKind.MONTHLY_SUMMARY

    def test_title_includes_customer_and_month(self) -> None:
        card = render_monthly_summary_card(_sample_data(customer_id="customerA", month="2026-05"))
        assert "customerA" in card.title
        assert "2026-05" in card.title

    def test_markdown_contains_key_metrics(self) -> None:
        card = render_monthly_summary_card(_sample_data())
        md = card.markdown
        # Money figures use thousands separators per project convention.
        assert "82,700" in md
        assert "15" in md  # total decisions
        assert "14" in md  # approved
        assert "93%" in md  # approval rate
        assert "6.6" in md  # ROI

    def test_markdown_lists_top_actions(self) -> None:
        card = render_monthly_summary_card(_sample_data())
        md = card.markdown
        # Action enum value should appear (e.g. 'transform', 'discount_clearance').
        assert "transform" in md
        assert "discount_clearance" in md

    def test_batch_id_anchors_to_month(self) -> None:
        """Card.batch_id is required; use the month as a stable identifier."""
        card = render_monthly_summary_card(_sample_data(month="2026-05"))
        assert card.batch_id == "monthly-2026-05"

    def test_no_buttons_or_mentions(self) -> None:
        card = render_monthly_summary_card(_sample_data())
        assert card.buttons == []
        assert card.mentioned_userids == []

    def test_handles_zero_decisions_gracefully(self) -> None:
        card = render_monthly_summary_card(
            _sample_data(
                total_count=0,
                approved_count=0,
                total_savings_estimate=0.0,
                total_savings_actual=0.0,
                roi_multiple=0.0,
            )
        )
        # The "approval rate 0%" branch is the off-nominal one — must still render.
        assert "0%" in card.markdown
        assert "0" in card.markdown
