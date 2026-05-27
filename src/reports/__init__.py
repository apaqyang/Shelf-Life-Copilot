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

__all__ = [
    "ActionTally",
    "MonthlyReportData",
    "aggregate_monthly_report",
    "render_monthly_report_pdf",
]
