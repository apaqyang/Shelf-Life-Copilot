"""One-shot CLI: run a single scan cycle for a customer and print results.

Usage:
    python -m src.cli --customer customerA [--today 2026-05-26] [--dry-run]
    python -m src.cli --customer customerA --provider moonshot --model moonshot-v1-32k
    python -m src.cli --customer customerA --revise-batch A-001 \\
        --feedback "虾饺线满了，能不能改成打折清仓"

`--dry-run` skips LLM calls. Otherwise the configured provider's API key is
required: ANTHROPIC_API_KEY (default) or MOONSHOT_API_KEY (--provider moonshot).

`--revise-batch BATCH_ID --feedback "..."` re-runs the LLM for a single batch
with operator feedback (PRD §5.3 改方案). Out-of-scope suggestions still come
back as the red-stamped card — the guard-rail is visible by design.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import date

from src.scheduler import ScanResult, ScanRunner
from src.suggestion import (
    ANTHROPIC_DEFAULT_MODEL,
    MOONSHOT_DEFAULT_MODEL,
    LLMProvider,
    SuggestionEngine,
    build_anthropic_provider,
    build_moonshot_provider,
)
from src.wecom import DryRunWecomClient, WebhookWecomClient, WecomClient

_PROVIDER_CHOICES = ("anthropic", "moonshot")


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
    parser.add_argument(
        "--provider",
        choices=_PROVIDER_CHOICES,
        default="anthropic",
        help="LLM provider (default: anthropic). moonshot uses Moonshot/KIMI via OpenAI protocol.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model id override. Defaults: claude-sonnet-4-6 / moonshot-v1-32k.",
    )
    parser.add_argument(
        "--revise-batch",
        default=None,
        help="Run single-batch revise for this batch id (requires --feedback).",
    )
    parser.add_argument(
        "--feedback",
        default=None,
        help='Operator feedback for --revise-batch, e.g. "改成打折清仓".',
    )
    parser.add_argument(
        "--push-webhook",
        default=None,
        help=(
            "WeCom group-bot webhook URL to push cards to. "
            "Falls back to env WECOM_WEBHOOK_URL when omitted. "
            "Without either, cards stay in-memory (DryRunWecomClient)."
        ),
    )
    return parser.parse_args(argv)


def _build_wecom_client(webhook_url: str | None) -> WecomClient:
    """Pick the WeCom transport: real webhook when a URL is configured, else DryRun.

    Resolution order: explicit CLI flag → WECOM_WEBHOOK_URL env → DryRun.
    """
    url = webhook_url or os.environ.get("WECOM_WEBHOOK_URL")
    if url:
        return WebhookWecomClient(url)
    return DryRunWecomClient()


def _build_provider(provider_name: str, model: str | None) -> LLMProvider | None:
    """Return a configured LLMProvider, or None if the required API key is missing."""
    if provider_name == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print(
                "ANTHROPIC_API_KEY not set. Pass --dry-run to skip LLM calls, "
                "or use --provider moonshot with MOONSHOT_API_KEY.",
                file=sys.stderr,
            )
            return None
        return build_anthropic_provider(api_key, model=model or ANTHROPIC_DEFAULT_MODEL)
    # moonshot
    api_key = os.environ.get("MOONSHOT_API_KEY")
    if not api_key:
        print(
            "MOONSHOT_API_KEY not set. Get one from https://platform.moonshot.cn/console/api-keys.",
            file=sys.stderr,
        )
        return None
    return build_moonshot_provider(api_key, model=model or MOONSHOT_DEFAULT_MODEL)


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

    if args.revise_batch is not None and args.feedback is None:
        print("--revise-batch requires --feedback to be set.", file=sys.stderr)
        return 2
    if args.revise_batch is not None and args.dry_run:
        print("--revise-batch needs an LLM call; cannot combine with --dry-run.", file=sys.stderr)
        return 2

    engine: SuggestionEngine | None = None
    if not args.dry_run:
        provider = _build_provider(args.provider, args.model)
        if provider is None:
            return 2
        engine = SuggestionEngine(provider=provider)

    runner = ScanRunner(engine=engine)

    if args.revise_batch is not None:
        result = await runner.revise_for_batch(
            args.customer,
            batch_id=args.revise_batch,
            feedback=args.feedback,
            today=args.today,
        )
        print(format_result(result))
        # Revise is always card-centric — push to whichever client is configured
        # (DryRun when no webhook, real WeCom group bot otherwise) and echo the markdown.
        client = _build_wecom_client(args.push_webhook)
        for card in result.cards:
            await client.send_card(card)
        print()
        print(format_cards(result))
        return 0

    result = await runner.run_for_customer(
        args.customer,
        today=args.today,
        skip_llm=args.dry_run,
    )
    print(format_result(result))

    # Push cards when either flag asks for it: --render-cards (echo) or --push-webhook
    # (real push). Resolves to DryRun when neither is wired, mirroring prior behavior.
    if args.render_cards or args.push_webhook or os.environ.get("WECOM_WEBHOOK_URL"):
        client = _build_wecom_client(args.push_webhook)
        for card in result.cards:
            await client.send_card(card)
        if args.render_cards:
            print()
            print(format_cards(result))

    return 0


def entrypoint() -> int:  # pragma: no cover
    return asyncio.run(main())


if __name__ == "__main__":
    sys.exit(entrypoint())
