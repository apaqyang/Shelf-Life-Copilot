"""Monthly PDF report pipeline.

Two-layer design:
- aggregator.py: list[Decision] → MonthlyReportData (pure, 100% testable)
- renderer.py:   MonthlyReportData → PDF bytes (reportlab)

The split lets us swap the rendering backend (HTML, slides, etc.) without
touching the business numbers.
"""

from src.reports.aggregator import (
    ActionTally,
    MonthlyReportData,
    aggregate_monthly_report,
)
from src.reports.renderer import render_monthly_report_pdf
from src.reports.runner import (
    ReportRunResult,
    previous_month,
    run_monthly_reports,
)
from src.reports.sources import load_decisions_from_sqlite

__all__ = [
    "ActionTally",
    "MonthlyReportData",
    "ReportRunResult",
    "aggregate_monthly_report",
    "load_decisions_from_sqlite",
    "previous_month",
    "render_monthly_report_pdf",
    "run_monthly_reports",
]
