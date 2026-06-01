"""Manually trigger the monthly report pipeline once.

Use this for:
- First-time sanity-check on a real customer's SQLite log
- Re-pushing last month's summary if the cron run was missed (laptop closed, etc.)
- Demo: show the director the same flow that runs automatically on day 1

Required env when --push is set: WECOM_WEBHOOK_URL (group bot webhook)

Run:
    uv run python tools/trigger_monthly_now.py            # write PDFs, print summaries
    uv run python tools/trigger_monthly_now.py --push     # also push to WeCom group
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.reports import ReportRunResult
from src.scheduler import MonthlyReportScheduler
from src.wecom import WebhookWecomClient, WecomPushError, render_monthly_summary_card

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "decisions.db"
DEFAULT_OUTPUT_DIR = ROOT / "docs" / "demo_samples"

# Same table as render_monthly_report.py — kept in sync intentionally; v1.0 will
# read this from a config file once we have more than two customers.
_ANNUAL_BASELINE_LOSS: dict[str, float] = {
    "customerA": 1_500_000.0,
    "customerB": 860_000.0,
}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="trigger-monthly-now", description=__doc__)
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    p.add_argument(
        "--push",
        action="store_true",
        help="Push summary cards to WECOM_WEBHOOK_URL (group bot).",
    )
    return p.parse_args(argv)


def _make_callback(
    push: bool,
) -> object:
    """Return an async on_result callback that prints + (optionally) pushes."""
    webhook_url = os.environ.get("WECOM_WEBHOOK_URL") if push else None
    client = WebhookWecomClient(webhook_url) if webhook_url else None
    if push and client is None:
        print(
            "WARNING: --push set but WECOM_WEBHOOK_URL is empty; skipping WeCom push.",
            file=sys.stderr,
        )

    async def _cb(r: ReportRunResult) -> None:
        if r.is_skipped:
            print(f"  {r.customer_id}: skipped ({r.skipped_reason})")
            return
        assert r.data is not None and r.pdf_path is not None
        print(
            f"  {r.customer_id}: wrote {r.pdf_path.relative_to(ROOT)}  "
            f"savings=¥{r.data.total_savings_actual:,.0f}  ROI={r.data.roi_multiple:.1f}x"
        )
        if client is not None:
            card = render_monthly_summary_card(r.data)
            try:
                await client.send_card(card)
                print(f"    pushed summary card to WeCom group ({card.title})")
            except WecomPushError as exc:
                print(f"    WeCom push failed: {exc}", file=sys.stderr)

    return _cb


async def _run(args: argparse.Namespace) -> int:
    sched = MonthlyReportScheduler(
        db_path=Path(args.db),
        output_dir=Path(args.output_dir),
        baselines=_ANNUAL_BASELINE_LOSS,
        on_result=_make_callback(args.push),  # type: ignore[arg-type]
    )
    print(f"Triggering monthly run · db={args.db} · output={args.output_dir}")
    await sched.run_now()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
