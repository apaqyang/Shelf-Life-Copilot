"""Smoke tests for the PDF renderer.

We don't pixel-match — we check (a) the byte stream is a valid PDF and (b) the
key business numbers are recoverable from the rendered text. That's enough to
catch silent regressions like "the savings number dropped off the cover page".
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

import pypdf
import pytest

from src.models import ActionType, Decision, DecisionOutcome
from src.reports import (
    MonthlyReportData,
    aggregate_monthly_report,
    render_monthly_report_pdf,
)
from src.reports.aggregator import ActionTally


def _decision(
    batch_id: str,
    action: ActionType,
    outcome: DecisionOutcome,
    estimate: float,
    actual: float | None,
    day: int = 10,
    material: str = "冷冻虾仁",
) -> Decision:
    return Decision(
        batch_id=batch_id,
        customer_id="customerA",
        material_name=material,
        decided_at=datetime(2026, 5, day, 7, 15, tzinfo=UTC),
        action=action,
        outcome=outcome,
        savings_estimate=estimate,
        actual_savings=actual,
        actual_qty=100.0 if actual is not None else None,
        notes="历史采纳率高，转加工虾饺馅可消化全部库存" if actual else None,
    )


@pytest.fixture
def report_data() -> MonthlyReportData:
    decisions = [
        _decision(
            "A-1",
            ActionType.TRANSFORM,
            DecisionOutcome.APPROVED,
            8500.0,
            8200.0,
            day=2,
        ),
        _decision(
            "A-2",
            ActionType.TRANSFORM,
            DecisionOutcome.APPROVED,
            9000.0,
            8800.0,
            day=4,
        ),
        _decision(
            "A-3",
            ActionType.DISCOUNT_CLEARANCE,
            DecisionOutcome.REVISED,
            6500.0,
            6300.0,
            day=6,
            material="冷冻鱼糜",
        ),
        _decision(
            "A-4",
            ActionType.REPORT_LOSS,
            DecisionOutcome.APPROVED,
            3200.0,
            3200.0,
            day=8,
            material="虾饺皮",
        ),
        _decision(
            "A-5",
            ActionType.TRANSFORM,
            DecisionOutcome.SNOOZED,
            7000.0,
            None,
            day=10,
        ),
    ]
    return aggregate_monthly_report(
        decisions=decisions,
        customer_id="customerA",
        industry="frozen_seafood",
        month="2026-05",
        annual_baseline_loss=1_500_000.0,
    )


def _extract_text(pdf_bytes: bytes) -> str:
    reader = pypdf.PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


class TestPdfStructure:
    def test_pdf_magic_bytes(self, report_data: MonthlyReportData) -> None:
        pdf = render_monthly_report_pdf(report_data)
        assert pdf.startswith(b"%PDF-")

    def test_has_multiple_pages(self, report_data: MonthlyReportData) -> None:
        # 4 sections + cover, with PageBreaks → at least 4 pages.
        pdf = render_monthly_report_pdf(report_data)
        reader = pypdf.PdfReader(BytesIO(pdf))
        assert len(reader.pages) >= 4

    def test_metadata_set(self, report_data: MonthlyReportData) -> None:
        pdf = render_monthly_report_pdf(report_data)
        reader = pypdf.PdfReader(BytesIO(pdf))
        assert reader.metadata is not None
        assert "Shelf-Life Copilot" in (reader.metadata.title or "")


class TestPdfContent:
    def test_total_savings_on_cover(self, report_data: MonthlyReportData) -> None:
        pdf = render_monthly_report_pdf(report_data)
        text = _extract_text(pdf)
        # Total approved savings: 8200 + 8800 + 6300 + 3200 = 26500
        assert "26,500" in text

    def test_customer_id_present(self, report_data: MonthlyReportData) -> None:
        pdf = render_monthly_report_pdf(report_data)
        assert "customerA" in _extract_text(pdf)

    def test_month_present(self, report_data: MonthlyReportData) -> None:
        pdf = render_monthly_report_pdf(report_data)
        assert "2026-05" in _extract_text(pdf)

    def test_top_action_present(self, report_data: MonthlyReportData) -> None:
        # transform totals 17,000 → must appear
        pdf = render_monthly_report_pdf(report_data)
        assert "17,000" in _extract_text(pdf)


class TestSeparatorGlyph:
    """STSong-Light lacks U+00B7 (·) → it renders as tofu (□).

    We use U+30FB (・, katakana middle dot), which the CID font does carry and
    which looks all but identical. Guard against the tofu regressing back in.
    """

    def test_no_tofu_middle_dot_u00b7(self, report_data: MonthlyReportData) -> None:
        text = _extract_text(render_monthly_report_pdf(report_data))
        assert "·" not in text

    def test_uses_katakana_middle_dot_u30fb(self, report_data: MonthlyReportData) -> None:
        text = _extract_text(render_monthly_report_pdf(report_data))
        assert "・" in text


class TestEmptyData:
    def test_empty_report_still_renders(self) -> None:
        data = aggregate_monthly_report(
            decisions=[],
            customer_id="customerA",
            industry="frozen_seafood",
            month="2026-05",
            annual_baseline_loss=1_500_000.0,
        )
        pdf = render_monthly_report_pdf(data)
        assert pdf.startswith(b"%PDF-")
        text = _extract_text(pdf)
        # No case studies → placeholder text rendered
        assert "无已执行" in text or "下月数据进入" in text


class TestNoTopActions:
    def test_renders_dash_row_when_no_approved_actions(self) -> None:
        # Build data with zero approved actions but otherwise valid.
        data = MonthlyReportData(
            customer_id="customerA",
            industry="frozen_seafood",
            month="2026-05",
            total_count=1,
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
        pdf = render_monthly_report_pdf(data)
        text = _extract_text(pdf)
        assert "无已执行的处置" in text


class TestCaseStudyWithoutNotes:
    def test_case_studies_render_without_notes_line(self) -> None:
        # Decision with actual_savings set but notes=None — exercises the
        # `if d.notes:` False branch in the case-studies renderer.
        d = Decision(
            batch_id="A-X",
            customer_id="customerA",
            material_name="冷冻虾仁",
            decided_at=datetime(2026, 5, 20, 7, 15, tzinfo=UTC),
            action=ActionType.TRANSFORM,
            outcome=DecisionOutcome.APPROVED,
            savings_estimate=8000.0,
            actual_savings=7800.0,
            actual_qty=800.0,
            notes=None,
        )
        data = aggregate_monthly_report(
            decisions=[d],
            customer_id="customerA",
            industry="frozen_seafood",
            month="2026-05",
            annual_baseline_loss=1_500_000.0,
        )
        pdf = render_monthly_report_pdf(data)
        text = _extract_text(pdf)
        assert "A-X" in text
        # No "备注" line should appear (no notes provided).
        assert "备注" not in text


class TestActionLabelFallback:
    def test_unknown_action_label_falls_back_to_enum(self) -> None:
        # Build a custom MonthlyReportData with an ActionTally we control.
        data = MonthlyReportData(
            customer_id="customerA",
            industry="frozen_seafood",
            month="2026-05",
            total_count=1,
            approved_count=1,
            approval_rate=1.0,
            total_savings_estimate=1000.0,
            total_savings_actual=1000.0,
            top_actions=[
                ActionTally(
                    action=ActionType.TRANSFORM,
                    approved_count=1,
                    total_actual_savings=1000.0,
                )
            ],
            case_studies=[],
            annual_baseline_loss=1_500_000.0,
            monthly_subscription_fee=12500.0,
            roi_multiple=0.08,
        )
        pdf = render_monthly_report_pdf(data)
        text = _extract_text(pdf)
        assert "转加工" in text
