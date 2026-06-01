"""Render monthly PDF reports for all customers.

Two sources for the underlying decision log:
  --source mock    (default)  — reads data/mock_history/<customer>.json
  --source sqlite             — reads from a DecisionStore at --db PATH

The mock source ships pre-canned demo numbers so `make report` always produces
a PDF without needing prior CLI activity. The sqlite source is the v0.5 path
once `--record-decision` accumulates real entries.

Run with:
    uv run python tools/render_monthly_report.py
    uv run python tools/render_monthly_report.py --source sqlite --month 2026-05
    # or: make report  /  make report SOURCE=sqlite MONTH=2026-05
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import Decision
from src.reports import (
    aggregate_monthly_report,
    load_decisions_from_sqlite,
    render_monthly_report_pdf,
)
from src.repository import load_customer_config

ROOT = Path(__file__).resolve().parent.parent
HISTORY_DIR = ROOT / "data" / "mock_history"
OUTPUT_DIR = ROOT / "docs" / "demo_samples"
DEFAULT_MONTH = "2026-05"
DEFAULT_DB = ROOT / "data" / "decisions.db"

# Annual baseline loss per customer — taken from PRD §3 锚定客户 table.
_ANNUAL_BASELINE_LOSS: dict[str, float] = {
    "customerA": 1_500_000.0,
    "customerB": 860_000.0,
}


def _load_decisions_from_mock(path: Path) -> list[Decision]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Decision.model_validate(item) for item in raw]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="render-monthly-report", description=__doc__)
    parser.add_argument(
        "--source",
        choices=("mock", "sqlite"),
        default="mock",
        help="Where to read decisions from (default: mock).",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB),
        help=f"SQLite path (used when --source sqlite). Default: {DEFAULT_DB.relative_to(ROOT)}.",
    )
    parser.add_argument(
        "--month",
        default=DEFAULT_MONTH,
        help=f"Report month YYYY-MM (default: {DEFAULT_MONTH}).",
    )
    return parser.parse_args(argv)


def _customers_with_mock_history() -> list[str]:
    return [p.stem for p in sorted(HISTORY_DIR.glob("*.json"))]


def _render_one(customer_id: str, decisions: list[Decision], month: str) -> Path | None:
    """Aggregate + write one customer's PDF. Returns the path, or None if skipped."""
    baseline = _ANNUAL_BASELINE_LOSS.get(customer_id)
    if baseline is None:
        print(f"skipping {customer_id}: no baseline configured", file=sys.stderr)
        return None
    if not decisions:
        print(f"skipping {customer_id}: no decisions found for {month}", file=sys.stderr)
        return None

    config = load_customer_config(customer_id)
    data = aggregate_monthly_report(
        decisions=decisions,
        customer_id=customer_id,
        industry=config.industry,
        month=month,
        annual_baseline_loss=baseline,
    )
    out = OUTPUT_DIR / f"monthly_report_{customer_id}.pdf"
    out.write_bytes(render_monthly_report_pdf(data))
    print(
        f"wrote {out.relative_to(ROOT)}  "
        f"(decisions={data.total_count}, savings=¥{data.total_savings_actual:,.0f}, "
        f"ROI={data.roi_multiple:.1f}x)"
    )
    return out


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.source == "mock":
        history_files = sorted(HISTORY_DIR.glob("*.json"))
        if not history_files:
            print(f"No history found in {HISTORY_DIR}", file=sys.stderr)
            return 1
        for path in history_files:
            customer_id = path.stem
            decisions = _load_decisions_from_mock(path)
            _render_one(customer_id, decisions, args.month)
        return 0

    # sqlite source — iterate the customer baseline table, not history files
    rendered_any = False
    for customer_id in _ANNUAL_BASELINE_LOSS:
        decisions = load_decisions_from_sqlite(args.db, customer_id, args.month)
        if _render_one(customer_id, decisions, args.month) is not None:
            rendered_any = True
    if not rendered_any:
        print(
            f"No decisions in {args.db} for any customer in {args.month}. "
            "Use `python -m src.cli --record-decision ...` to populate it.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
