"""Render monthly PDF reports for all customers with mock history.

For each customer with `data/mock_history/<customer>.json`:
  1. Load decisions
  2. Load CustomerConfig (for industry + annual_baseline_loss derived from the
     mock data's customer year-loss table)
  3. Aggregate → MonthlyReportData
  4. Render PDF → docs/demo_samples/monthly_report_<customer>.pdf

Run with:
    uv run python tools/render_monthly_report.py
    # or: make report
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import Decision
from src.reports import aggregate_monthly_report, render_monthly_report_pdf
from src.repository import load_customer_config

ROOT = Path(__file__).resolve().parent.parent
HISTORY_DIR = ROOT / "data" / "mock_history"
OUTPUT_DIR = ROOT / "docs" / "demo_samples"
REPORT_MONTH = "2026-05"

# Annual baseline loss per customer — taken from PRD §3 锚定客户 table.
_ANNUAL_BASELINE_LOSS: dict[str, float] = {
    "customerA": 1_500_000.0,
    "customerB": 860_000.0,
}


def _load_decisions(path: Path) -> list[Decision]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Decision.model_validate(item) for item in raw]


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    history_files = sorted(HISTORY_DIR.glob("*.json"))
    if not history_files:
        print(f"No history found in {HISTORY_DIR}", file=sys.stderr)
        return 1
    for path in history_files:
        customer_id = path.stem
        baseline = _ANNUAL_BASELINE_LOSS.get(customer_id)
        if baseline is None:
            print(f"skipping {customer_id}: no baseline configured", file=sys.stderr)
            continue
        config = load_customer_config(customer_id)
        decisions = _load_decisions(path)
        data = aggregate_monthly_report(
            decisions=decisions,
            customer_id=customer_id,
            industry=config.industry,
            month=REPORT_MONTH,
            annual_baseline_loss=baseline,
        )
        out = OUTPUT_DIR / f"monthly_report_{customer_id}.pdf"
        out.write_bytes(render_monthly_report_pdf(data))
        print(
            f"wrote {out.relative_to(ROOT)}  "
            f"(decisions={data.total_count}, savings=¥{data.total_savings_actual:,.0f}, "
            f"ROI={data.roi_multiple:.1f}x)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
