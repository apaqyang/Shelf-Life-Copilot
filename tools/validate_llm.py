"""Real-LLM compliance validator — PRD §9.1 行动集合合规率 100% gate.

Runs the configured provider against every alert-triggering batch for both
customers, plus 2 改方案 scenarios (one within bounds, one out-of-scope).
Reports per-call: latency, action chosen, is_standard, confidence, errors.
Aggregates: success rate, compliance rate (action ∈ enabled set), p50/p95 latency.

Usage:
    # KIMI / Moonshot
    MOONSHOT_API_KEY=sk-... uv run python tools/validate_llm.py --provider moonshot

    # Anthropic
    ANTHROPIC_API_KEY=sk-... uv run python tools/validate_llm.py --provider anthropic

    # Pin a specific model:
    MOONSHOT_API_KEY=sk-... uv run python tools/validate_llm.py --provider moonshot --model kimi-latest
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.alerts import scan_batch
from src.models import Alert, Batch, CustomerConfig
from src.repository import load_batches, load_customer_config
from src.suggestion import (
    ANTHROPIC_DEFAULT_MODEL,
    MOONSHOT_DEFAULT_MODEL,
    LLMProvider,
    SuggestionEngine,
    SuggestionEngineError,
    build_anthropic_provider,
    build_moonshot_provider,
)

VALIDATION_DATE = date(2026, 5, 26)


@dataclass
class CallRecord:
    """One LLM call outcome, serializable for the JSON report."""

    scenario: str  # "alert" / "revise_standard" / "revise_out_of_scope"
    customer_id: str
    batch_id: str
    material_name: str
    days_left: int
    feedback: str | None
    success: bool
    elapsed_ms: float
    action: str | None
    is_standard: bool | None
    confidence: float | None
    error: str | None


def _build(provider_name: str, model: str | None) -> LLMProvider:
    if provider_name == "anthropic":
        api_key = os.environ["ANTHROPIC_API_KEY"]
        return build_anthropic_provider(api_key, model=model or ANTHROPIC_DEFAULT_MODEL)
    api_key = os.environ["MOONSHOT_API_KEY"]
    return build_moonshot_provider(api_key, model=model or MOONSHOT_DEFAULT_MODEL)


async def _one_call(
    engine: SuggestionEngine,
    batch: Batch,
    alert: Alert,
    config: CustomerConfig,
    scenario: str,
    feedback: str | None,
) -> CallRecord:
    start = time.perf_counter()
    try:
        suggestion = await engine.suggest(batch, alert, config, feedback=feedback)
    except SuggestionEngineError as exc:
        return CallRecord(
            scenario=scenario,
            customer_id=batch.customer_id,
            batch_id=batch.batch_id,
            material_name=batch.material_name,
            days_left=alert.days_left,
            feedback=feedback,
            success=False,
            elapsed_ms=(time.perf_counter() - start) * 1000,
            action=None,
            is_standard=None,
            confidence=None,
            error=str(exc),
        )
    return CallRecord(
        scenario=scenario,
        customer_id=batch.customer_id,
        batch_id=batch.batch_id,
        material_name=batch.material_name,
        days_left=alert.days_left,
        feedback=feedback,
        success=True,
        elapsed_ms=(time.perf_counter() - start) * 1000,
        action=suggestion.action.value,
        is_standard=suggestion.is_standard,
        confidence=suggestion.confidence,
        error=None,
    )


async def _validate_customer(
    engine: SuggestionEngine,
    customer_id: str,
    revise_feedback_in: str,
    revise_feedback_out: str,
) -> list[CallRecord]:
    config = load_customer_config(customer_id)
    batches = load_batches(customer_id)
    records: list[CallRecord] = []

    # 1) One LLM call per triggered alert.
    triggered = []
    for batch in batches:
        alert = scan_batch(batch, config.alert_thresholds, today=VALIDATION_DATE)
        if alert is not None:
            triggered.append((batch, alert))

    for batch, alert in triggered:
        records.append(await _one_call(engine, batch, alert, config, "alert", None))

    if not triggered:
        return records

    # 2) Two 改方案 calls on the first triggered batch — in-scope and out-of-scope.
    headline_batch, headline_alert = triggered[0]
    records.append(
        await _one_call(
            engine,
            headline_batch,
            headline_alert,
            config,
            "revise_in_scope",
            revise_feedback_in,
        )
    )
    records.append(
        await _one_call(
            engine,
            headline_batch,
            headline_alert,
            config,
            "revise_out_of_scope",
            revise_feedback_out,
        )
    )
    return records


def _summarize(records: list[CallRecord], provider_name: str, model: str) -> dict[str, Any]:
    total = len(records)
    success = [r for r in records if r.success]
    success_rate = len(success) / total if total else 0.0
    # Compliance: among successful calls, fraction where is_standard is True.
    # (out_of_scope feedback may intentionally yield False — kept as a separate counter.)
    in_scope = [r for r in success if r.scenario != "revise_out_of_scope"]
    compliant = [r for r in in_scope if r.is_standard]
    compliance_rate = len(compliant) / len(in_scope) if in_scope else 0.0
    out_of_scope_calls = [r for r in success if r.scenario == "revise_out_of_scope"]
    latencies = [r.elapsed_ms for r in success]
    return {
        "provider": provider_name,
        "model": model,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_calls": total,
        "successful_calls": len(success),
        "failed_calls": total - len(success),
        "success_rate": round(success_rate, 4),
        "compliance_rate_in_scope": round(compliance_rate, 4),
        "in_scope_calls": len(in_scope),
        "out_of_scope_calls": len(out_of_scope_calls),
        "out_of_scope_correctly_flagged": sum(
            1 for r in out_of_scope_calls if r.is_standard is False
        ),
        "latency_ms_p50": round(statistics.median(latencies), 1) if latencies else None,
        "latency_ms_p95": round(_p95(latencies), 1) if latencies else None,
        "latency_ms_max": round(max(latencies), 1) if latencies else None,
        "records": [asdict(r) for r in records],
    }


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, int(len(s) * 0.95) - 1)
    return s[idx]


def _print_summary(summary: dict[str, Any]) -> None:
    print()
    print("=" * 72)
    print(f"LLM 验证报告  provider={summary['provider']}  model={summary['model']}")
    print("=" * 72)
    print(f"总调用数            : {summary['total_calls']}")
    print(
        f"成功 / 失败          : {summary['successful_calls']} / {summary['failed_calls']}"
        f"  (成功率 {summary['success_rate']:.0%})"
    )
    print(
        f"动作合规率（in-scope）: {summary['compliance_rate_in_scope']:.0%}  "
        f"({summary['in_scope_calls']} 次)"
    )
    print(
        f"越界场景正确打标      : {summary['out_of_scope_correctly_flagged']} / "
        f"{summary['out_of_scope_calls']}"
    )
    if summary["latency_ms_p50"] is not None:
        print(
            f"延迟 p50 / p95 / max  : {summary['latency_ms_p50']} / "
            f"{summary['latency_ms_p95']} / {summary['latency_ms_max']} ms"
        )
    print()
    print("--- 调用明细 ---")
    for r in summary["records"]:
        tag = "✅" if r["success"] else "❌"
        std = "" if r["is_standard"] in (None, True) else " ⚠️非标准"
        print(
            f"  {tag} [{r['scenario']:>20}] {r['customer_id']} "
            f"{r['batch_id']} ({r['material_name']}, 剩余 {r['days_left']} 天) "
            f"→ {r['action'] or '—'}{std} "
            f"conf={r['confidence']} | {r['elapsed_ms']:.0f}ms"
            + (f" | err={r['error']}" if r["error"] else "")
        )


async def main() -> int:
    parser = argparse.ArgumentParser(prog="validate-llm")
    parser.add_argument("--provider", choices=("anthropic", "moonshot"), default="anthropic")
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent.parent
        / "docs"
        / "demo_samples"
        / "llm_validation_report.json",
        help="Where to write the JSON report.",
    )
    args = parser.parse_args()

    env_key = "ANTHROPIC_API_KEY" if args.provider == "anthropic" else "MOONSHOT_API_KEY"
    if not os.environ.get(env_key):
        print(f"{env_key} not set — cannot validate {args.provider}.", file=sys.stderr)
        return 2

    provider = _build(args.provider, args.model)
    engine = SuggestionEngine(provider=provider)

    records: list[CallRecord] = []
    records.extend(
        await _validate_customer(
            engine,
            "customerA",
            revise_feedback_in="虾饺线满了，能不能改成打折清仓",
            revise_feedback_out="送给关联食堂内部消化掉",  # employee_canteen disabled for A
        )
    )
    records.extend(
        await _validate_customer(
            engine,
            "customerB",
            revise_feedback_in="食堂这周菜单锁定了，改成打折清仓",
            revise_feedback_out="能不能转加工成新菜品",  # transform disabled for customerB
        )
    )

    summary = _summarize(records, args.provider, provider.model_name)
    _print_summary(summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"报告已写入：{args.output.relative_to(Path.cwd())}")

    # Exit non-zero if compliance gate fails (PRD §9.1 = 100%).
    if summary["compliance_rate_in_scope"] < 1.0:
        print(
            f"⚠️ compliance gate failed: {summary['compliance_rate_in_scope']:.0%} < 100%",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
