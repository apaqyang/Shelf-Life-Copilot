"""Sales lead qualifier — 8-question survey CLI (PRD §12.1).

Three modes:
  interactive  (default)  — prompt sales rep for each answer in terminal
  --answers PATH          — read LeadAnswers from JSON (testing / batch)
  --reassess PATH         — re-run scoring against a previously written
                            LeadAssessment JSON (edit raw_answers in place)

Outputs:
  - markdown summary printed to stdout (sales reads immediately)
  - data/leads/<slug>_<YYYYMMDD>.json  for CRM hand-off
  - data/leads/<slug>_<YYYYMMDD>.pdf   one-pager (unless --no-pdf)

Run:
    uv run python tools/qualify_lead.py
    uv run python tools/qualify_lead.py --answers fresh_lead.json
    uv run python tools/qualify_lead.py --reassess data/leads/客户A_20260601.json
    # or: make qualify
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.sales import (
    AnnualLossBand,
    ContactInfo,
    CurrentMethod,
    DecisionAuthority,
    IndustryCategory,
    LeadAnswers,
    LeadAssessment,
    assess_lead,
    extract_answers_from_assessment_json,
    render_lead_pdf,
)
from src.sales.report import render_assessment_markdown

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = ROOT / "data" / "leads"


# ── Interactive helpers ───────────────────────────────────────────────────


def _prompt_enum(prompt: str, enum_cls: type) -> str:
    """Show numbered options for a StrEnum, return the picked .value."""
    members = list(enum_cls)
    print(f"\n{prompt}")
    for i, m in enumerate(members, start=1):
        print(f"  {i}. {m.value}")
    while True:
        raw = input(f"选择 (1-{len(members)}): ").strip()
        try:
            idx = int(raw)
        except ValueError:
            print("请输入数字")
            continue
        if 1 <= idx <= len(members):
            return members[idx - 1].value
        print("超出范围")


def _prompt_text(prompt: str) -> str:
    while True:
        v = input(f"{prompt}: ").strip()
        if v:
            return v
        print("不能为空")


def _prompt_optional_float(prompt: str) -> float | None:
    raw = input(f"{prompt} (留空跳过): ").strip()
    if not raw:
        return None
    return float(raw)


def _collect_interactive() -> LeadAnswers:
    """Walk the user through the 8 questions in PRD §12.1 order."""
    print("=" * 60)
    print("Shelf-Life Copilot · 销售线索评估问卷（5 分钟 8 题）")
    print("=" * 60)

    customer_name = _prompt_text("客户公司名（必填）")
    industry = _prompt_enum("Q1. 贵司主营产品品类？", IndustryCategory)
    annual_procurement_band = _prompt_text(
        "Q2. 年原料/半成品采购总额？（如 < 1亿 / 1-5亿 / 5-20亿 / > 20亿）"
    )
    sku_count_band = _prompt_text("Q3. 原料 SKU 数？（如 < 200 / 200-1000 / 1000-5000 / > 5000）")
    avg_shelf_life_band = _prompt_text(
        "Q4. 主要原料平均保质期？（如 < 30天 / 30-90天 / 90天-1年 / > 1年）"
    )

    annual_loss_band = _prompt_enum("Q5. 去年报损/临期处置金额？", AnnualLossBand)
    monthly_loss_estimate: float | None = None
    if annual_loss_band == AnnualLossBand.UNKNOWN.value:
        monthly_loss_estimate = _prompt_optional_float(
            "Q6. 月发生临期处置的金额估算（元，Q5 答不出时必填）"
        )

    current_method = _prompt_enum("Q7. 当前临期管理方式？", CurrentMethod)
    decision_authority = _prompt_enum("Q8. 处置决策由谁拍板？", DecisionAuthority)

    return LeadAnswers(
        customer_name=customer_name,
        industry=IndustryCategory(industry),
        annual_procurement_band=annual_procurement_band,
        sku_count_band=sku_count_band,
        avg_shelf_life_band=avg_shelf_life_band,
        annual_loss_band=AnnualLossBand(annual_loss_band),
        monthly_loss_estimate_yuan=monthly_loss_estimate,
        current_method=CurrentMethod(current_method),
        decision_authority=DecisionAuthority(decision_authority),
    )


# ── Non-interactive (JSON file) path ──────────────────────────────────────


def _load_answers_from_json(path: Path) -> LeadAnswers:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return LeadAnswers.model_validate(raw)


def _load_answers_from_assessment(path: Path) -> LeadAnswers:
    """Pull raw_answers out of a previously written LeadAssessment JSON."""
    return extract_answers_from_assessment_json(path.read_text(encoding="utf-8"))


# ── Output helpers ────────────────────────────────────────────────────────


def _slugify(name: str) -> str:
    """Replace non-alphanumerics (including Chinese punctuation) with hyphens.

    Chinese characters are kept as-is — filesystem handles UTF-8 fine and the
    operator wants to see "客户A" not "客户a" or transliterated noise.
    """
    cleaned = re.sub(r"[^\w一-鿿]+", "-", name, flags=re.UNICODE).strip("-")
    return cleaned or "lead"


def _write_record(assessment: LeadAssessment, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    today = assessment.assessed_at.strftime("%Y%m%d")
    out = output_dir / f"{_slugify(assessment.customer_name)}_{today}.json"
    out.write_text(
        assessment.model_dump_json(indent=2, exclude_none=False),
        encoding="utf-8",
    )
    return out


# ── Entry point ───────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="qualify-lead", description=__doc__)
    p.add_argument(
        "--answers",
        type=Path,
        default=None,
        help="Path to a JSON file with LeadAnswers (skips interactive prompts).",
    )
    p.add_argument(
        "--reassess",
        type=Path,
        default=None,
        help=(
            "Path to a previously written LeadAssessment JSON; re-runs scoring "
            "against its raw_answers (edit a field in the file, then re-run)."
        ),
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Where to write outputs (default: {DEFAULT_OUTPUT_DIR.relative_to(ROOT)}).",
    )
    p.add_argument(
        "--no-pdf",
        action="store_true",
        help="Skip the ROI one-pager PDF (default: write one alongside the JSON record).",
    )
    p.add_argument("--contact-name", default=None, help="Sales rep name on the PDF.")
    p.add_argument("--contact-phone", default=None, help="Sales rep phone on the PDF.")
    p.add_argument("--contact-email", default=None, help="Sales rep email on the PDF.")
    return p.parse_args(argv)


def _build_contact(args: argparse.Namespace) -> ContactInfo | None:
    """Build a ContactInfo only if at least the name was supplied."""
    if args.contact_name is None:
        return None
    return ContactInfo(
        name=args.contact_name,
        phone=args.contact_phone,
        email=args.contact_email,
    )


def _write_pdf(
    assessment: LeadAssessment,
    contact: ContactInfo | None,
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    today = assessment.assessed_at.strftime("%Y%m%d")
    out = output_dir / f"{_slugify(assessment.customer_name)}_{today}.pdf"
    out.write_bytes(render_lead_pdf(assessment, contact=contact))
    return out


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.answers is not None and args.reassess is not None:
        print("--answers and --reassess are mutually exclusive.", file=sys.stderr)
        return 2

    if args.reassess is not None:
        answers = _load_answers_from_assessment(args.reassess)
    elif args.answers is not None:
        answers = _load_answers_from_json(args.answers)
    else:
        answers = _collect_interactive()

    # Stamp assessed_at deterministically with UTC now so the JSON record can
    # be diffed across runs (slug already carries date).
    assessment = assess_lead(answers).model_copy(update={"assessed_at": datetime.now(UTC)})

    print()
    print(render_assessment_markdown(assessment))

    record_path = _write_record(assessment, args.output_dir)
    print(f"\nJSON 留档已写入：{record_path}")

    if not args.no_pdf:
        pdf_path = _write_pdf(assessment, _build_contact(args), args.output_dir)
        print(f"ROI 一页纸 PDF 已写入：{pdf_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
