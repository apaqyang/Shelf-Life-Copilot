"""One-shot CLI: run a single scan cycle for a customer and print results.

Usage:
    python -m src.cli --customer customerA [--today 2026-05-26] [--dry-run]

`--dry-run` skips LLM calls and prints alerts only — useful when ANTHROPIC_API_KEY
is not configured, or for quick determinism checks against the mock data.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import date

from anthropic import AsyncAnthropic

from src.scheduler import ScanResult, ScanRunner
from src.suggestion import SuggestionEngine
from src.wecom import DryRunWecomClient


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="shelf-life-copilot",
        description="Run one scan cycle for a customer and print the result.",
    )
    parser.add_argument(
        "--customer",
        required=True,
        help="Customer ID (matching a file in data/batches/<id>.json).",
    )
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=None,
        help="Override today's date (YYYY-MM-DD) for deterministic demos.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip LLM calls and print alerts only (no API key required).",
    )
    parser.add_argument(
        "--render-cards",
        action="store_true",
        help="After the scan, print each rendered WeCom card markdown to stdout.",
    )
    return parser.parse_args(argv)


def format_result(result: ScanResult) -> str:
    """Pretty-print a ScanResult as a multi-line block for the terminal."""
    lines = [
        f"=== Scan result for {result.customer_id} ===",
        f"Total batches: {result.total_batches}",
        f"Alerts:        {len(result.alerts)}",
        f"Suggestions:   {len(result.suggestions)}",
        f"Errors:        {len(result.errors)}",
        "",
    ]

    if not result.alerts:
        lines.append("(no alerts — all batches are safely above thresholds)")
        return "\n".join(lines)

    lines.append("--- Alerts ---")
    for alert in result.alerts:
        lines.append(
            f"  [{alert.severity.value:>6}] batch {alert.batch_id}  剩余 {alert.days_left} 天"
        )

    if result.suggestions:
        lines.append("")
        lines.append("--- Suggestions ---")
        for s in result.suggestions:
            tag = "" if s.is_standard else "  ⚠️ 非标准动作"
            lines.append(
                f"  batch {s.batch_id}: {s.action.value}"
                f" → 省 ¥{s.savings_estimate:,.0f}"
                f" (置信度 {s.confidence:.0%}){tag}"
            )
            lines.append(f"    rationale: {s.rationale}")

    if result.errors:
        lines.append("")
        lines.append("--- Errors ---")
        for e in result.errors:
            lines.append(f"  batch {e.batch_id}: {e.message}")

    return "\n".join(lines)


def format_cards(result: ScanResult) -> str:
    """Render every Card in a ScanResult as separator-delimited blocks."""
    if not result.cards:
        return "(no cards — pass without --dry-run to generate suggestions)"
    blocks = ["=== Rendered cards ==="]
    for i, card in enumerate(result.cards, start=1):
        blocks.append(f"\n--- Card #{i} · {card.kind.value} · {card.title} ---")
        blocks.append(card.markdown)
    return "\n".join(blocks)


async def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = parse_args(argv)

    engine: SuggestionEngine | None = None
    if not args.dry_run:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print(
                "ANTHROPIC_API_KEY not set. Pass --dry-run to skip LLM calls.",
                file=sys.stderr,
            )
            return 2
        engine = SuggestionEngine(client=AsyncAnthropic(api_key=api_key))  # pragma: no cover

    runner = ScanRunner(engine=engine)
    result = await runner.run_for_customer(
        args.customer,
        today=args.today,
        skip_llm=args.dry_run,
    )
    print(format_result(result))

    if args.render_cards:
        # Dry-run push to a no-op WeCom client — exercises the send_card surface
        # so we can validate the wiring offline (real client lands in v0.5).
        client = DryRunWecomClient()
        for card in result.cards:
            await client.send_card(card)
        print()
        print(format_cards(result))

    return 0


def entrypoint() -> int:  # pragma: no cover
    return asyncio.run(main())


if __name__ == "__main__":
    sys.exit(entrypoint())
