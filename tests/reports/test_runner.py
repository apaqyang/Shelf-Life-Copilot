"""Tests for the monthly-report runner (SQLite → PDF orchestration).

Layered separately from the scheduler so cron-trigger glue stays thin and the
business logic stays testable without APScheduler in the loop.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from src.models import ActionType, Decision, DecisionOutcome
from src.persistence import DecisionStore
from src.reports.runner import (
    ReportRunResult,
    previous_month,
    run_monthly_reports,
)


def _decision(
    *,
    customer_id: str = "customerA",
    batch_id: str = "A-001",
    decided_at: datetime,
    savings: float = 8500.0,
) -> Decision:
    return Decision(
        batch_id=batch_id,
        customer_id=customer_id,
        material_name="冷冻虾仁",
        decided_at=decided_at,
        action=ActionType.TRANSFORM,
        outcome=DecisionOutcome.APPROVED,
        savings_estimate=savings,
        actual_savings=savings,
        actual_qty=100.0,
    )


class TestPreviousMonth:
    def test_mid_year(self) -> None:
        assert previous_month(date(2026, 6, 1)) == "2026-05"

    def test_february_rolls_to_previous_january(self) -> None:
        assert previous_month(date(2026, 2, 15)) == "2026-01"

    def test_january_rolls_to_previous_december(self) -> None:
        assert previous_month(date(2027, 1, 1)) == "2026-12"


class TestRunMonthlyReports:
    def test_skips_customers_with_no_decisions(self, tmp_path: Path) -> None:
        db = tmp_path / "d.db"
        DecisionStore(db)  # empty store

        out = tmp_path / "out"
        results = run_monthly_reports(
            today=date(2026, 6, 1),
            db_path=db,
            output_dir=out,
            baselines={"customerA": 1_500_000.0},
        )
        assert len(results) == 1
        r = results[0]
        assert r.customer_id == "customerA"
        assert r.is_skipped
        assert "no decisions" in (r.skipped_reason or "")
        assert r.pdf_path is None

    def test_generates_pdf_for_customer_with_data(self, tmp_path: Path) -> None:
        db = tmp_path / "d.db"
        store = DecisionStore(db)
        store.save(_decision(decided_at=datetime(2026, 5, 10, tzinfo=UTC)))
        store.save(_decision(batch_id="A-002", decided_at=datetime(2026, 5, 20, tzinfo=UTC)))

        out = tmp_path / "out"
        results = run_monthly_reports(
            today=date(2026, 6, 1),
            db_path=db,
            output_dir=out,
            baselines={"customerA": 1_500_000.0},
        )
        assert len(results) == 1
        r = results[0]
        assert not r.is_skipped
        assert r.pdf_path is not None
        assert r.pdf_path.exists()
        assert r.pdf_path.read_bytes().startswith(b"%PDF")
        assert r.data is not None
        assert r.data.total_count == 2

    def test_creates_output_dir_if_missing(self, tmp_path: Path) -> None:
        db = tmp_path / "d.db"
        store = DecisionStore(db)
        store.save(_decision(decided_at=datetime(2026, 5, 10, tzinfo=UTC)))

        out = tmp_path / "nested" / "out"  # doesn't exist yet
        assert not out.exists()
        run_monthly_reports(
            today=date(2026, 6, 1),
            db_path=db,
            output_dir=out,
            baselines={"customerA": 1_500_000.0},
        )
        assert out.is_dir()

    def test_customer_outside_baseline_table_is_not_processed(self, tmp_path: Path) -> None:
        db = tmp_path / "d.db"
        store = DecisionStore(db)
        store.save(_decision(customer_id="customerC", decided_at=datetime(2026, 5, 10, tzinfo=UTC)))

        out = tmp_path / "out"
        results = run_monthly_reports(
            today=date(2026, 6, 1),
            db_path=db,
            output_dir=out,
            baselines={"customerA": 1_500_000.0},  # customerC not in baselines
        )
        # Only customerA was attempted (it's the only baseline), and it's empty → skipped.
        assert [r.customer_id for r in results] == ["customerA"]
        assert results[0].is_skipped

    def test_supports_january_year_wrap(self, tmp_path: Path) -> None:
        db = tmp_path / "d.db"
        store = DecisionStore(db)
        # Decision in Dec 2026 must show up when running on 2027-01-01.
        store.save(_decision(decided_at=datetime(2026, 12, 31, 23, 0, tzinfo=UTC)))

        out = tmp_path / "out"
        results = run_monthly_reports(
            today=date(2027, 1, 1),
            db_path=db,
            output_dir=out,
            baselines={"customerA": 1_500_000.0},
        )
        assert results[0].data is not None
        assert results[0].data.month == "2026-12"


class TestReportRunResultModel:
    def test_is_skipped_when_reason_present(self, tmp_path: Path) -> None:
        r = ReportRunResult(customer_id="x", pdf_path=None, data=None, skipped_reason="empty")
        assert r.is_skipped

    def test_not_skipped_when_pdf_produced(self, tmp_path: Path) -> None:
        # data=None still counts as not-skipped if pdf_path is set — keeps the
        # invariant simple: skipped_reason is the single source of truth.
        r = ReportRunResult(
            customer_id="x", pdf_path=tmp_path / "x.pdf", data=None, skipped_reason=None
        )
        assert not r.is_skipped
