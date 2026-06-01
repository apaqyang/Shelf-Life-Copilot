"""Monthly report orchestrator — SQLite → aggregate → PDF, per customer.

This is the business-logic core invoked by both the CLI tool (manual run) and
the APScheduler-driven `MonthlyReportScheduler` (cron run). Pure-ish: only
side effects are reading from sqlite and writing the PDF file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.reports.aggregator import MonthlyReportData, aggregate_monthly_report
from src.reports.renderer import render_monthly_report_pdf
from src.reports.sources import load_decisions_from_sqlite
from src.repository import load_customer_config


@dataclass(frozen=True)
class ReportRunResult:
    """One customer's outcome from a monthly report run."""

    customer_id: str
    pdf_path: Path | None
    data: MonthlyReportData | None
    skipped_reason: str | None

    @property
    def is_skipped(self) -> bool:
        return self.skipped_reason is not None


def previous_month(today: date) -> str:
    """Return the month before `today` as 'YYYY-MM'. Handles January year-wrap."""
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


def run_monthly_reports(
    *,
    today: date,
    db_path: Path | str,
    output_dir: Path,
    baselines: dict[str, float],
) -> list[ReportRunResult]:
    """Aggregate + render PDFs for the previous month, one per customer in `baselines`."""
    month = previous_month(today)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[ReportRunResult] = []
    for customer_id, baseline in baselines.items():
        decisions = load_decisions_from_sqlite(db_path, customer_id, month)
        if not decisions:
            results.append(
                ReportRunResult(
                    customer_id=customer_id,
                    pdf_path=None,
                    data=None,
                    skipped_reason=f"no decisions in {month}",
                )
            )
            continue

        config = load_customer_config(customer_id)
        data = aggregate_monthly_report(
            decisions=decisions,
            customer_id=customer_id,
            industry=config.industry,
            month=month,
            annual_baseline_loss=baseline,
        )
        pdf_path = output_dir / f"monthly_report_{customer_id}.pdf"
        pdf_path.write_bytes(render_monthly_report_pdf(data))
        results.append(
            ReportRunResult(
                customer_id=customer_id,
                pdf_path=pdf_path,
                data=data,
                skipped_reason=None,
            )
        )

    return results
