"""Lead qualification rules — implements PRD §12.1 verbatim.

Pure functions; no I/O. Tests pin every PRD row so changes to sales math come
through code review, not folklore.
"""

from __future__ import annotations

from src.models import ActionType
from src.sales.models import (
    AnnualLossBand,
    CurrentMethod,
    DecisionAuthority,
    IndustryCategory,
    LeadAnswers,
    LeadAssessment,
    PriorityTier,
)

# v1.0 annual-fee table (PRD §11.2). The "议价 起步 25 万" line is encoded as
# 250_000 — sales can negotiate up from there with the customer's CTO.
_FEE_BY_BAND: dict[AnnualLossBand, float] = {
    AnnualLossBand.UNDER_50W: 80_000.0,
    AnnualLossBand.BETWEEN_50_100W: 80_000.0,
    AnnualLossBand.BETWEEN_100_300W: 150_000.0,
    AnnualLossBand.OVER_300W: 250_000.0,
}

# Mid-of-range estimate for each band, used in ROI math. Conservative-end-of-range
# would underplay the pitch; max-end would inflate it. The middle keeps the
# numbers defensible if sales is asked "where does that come from".
_LOSS_ESTIMATE_BY_BAND: dict[AnnualLossBand, float] = {
    AnnualLossBand.UNDER_50W: 300_000.0,  # 25 万 midpoint of < 50 万 (skewed up — < 50 not zero)
    AnnualLossBand.BETWEEN_50_100W: 750_000.0,  # 75 万 midpoint
    AnnualLossBand.BETWEEN_100_300W: 2_000_000.0,  # 200 万 midpoint
    AnnualLossBand.OVER_300W: 4_000_000.0,  # 400 万 conservative anchor
}

# Pitch lines lifted from PRD §12.1's sales-script table.
_PITCH_BY_BAND: dict[AnnualLossBand, str] = {
    AnnualLossBand.UNDER_50W: '"相当于年损的 8-10%，AI 帮您降 30% 就回本 5-6 倍"',
    AnnualLossBand.BETWEEN_50_100W: '"相当于年损的 8-10%，AI 帮您降 30% 就回本 5-6 倍"',
    AnnualLossBand.BETWEEN_100_300W: '"相当于年损的 5-8%，降 30% 回本 4-6 倍"',
    AnnualLossBand.OVER_300W: "走单独 ROI 测算 + 高管对接（议价起步 25 万）",
}

# Q1 → suggested PoC action subset. report_loss is the universal fallback —
# every customer needs "认输报损" as an option, so it's appended to every list.
_ACTIONS_BY_INDUSTRY: dict[IndustryCategory, list[ActionType]] = {
    IndustryCategory.FROZEN_RAW: [
        ActionType.TRANSFORM,
        ActionType.DISCOUNT_CLEARANCE,
    ],
    IndustryCategory.READY_MEAL: [
        ActionType.DISCOUNT_CLEARANCE,
        ActionType.EMPLOYEE_CANTEEN,
    ],
    IndustryCategory.BAKERY: [
        ActionType.DISCOUNT_CLEARANCE,
        ActionType.EMPLOYEE_CANTEEN,
    ],
    IndustryCategory.SNACKS: [
        ActionType.DISCOUNT_CLEARANCE,
    ],
    IndustryCategory.FRESH_PROCESSING: [
        ActionType.TRANSFORM,
        ActionType.EMPLOYEE_CANTEEN,
    ],
    IndustryCategory.OTHER: [
        ActionType.TRANSFORM,
        ActionType.DISCOUNT_CLEARANCE,
        ActionType.EMPLOYEE_CANTEEN,
        ActionType.TRANSFER_WAREHOUSE,
    ],
}

# How sales math turns 年损 into 节省 — PRD calls this out as "采纳率 60% × 减损率 30%".
_ADOPTION_RATE = 0.60
_LOSS_REDUCTION_RATE = 0.30


def _infer_band_from_annual(annual_loss: float) -> AnnualLossBand:
    """Map a numeric annual loss back into PRD's Q5 band — used for Q5=UNKNOWN."""
    if annual_loss < 500_000:
        return AnnualLossBand.UNDER_50W
    if annual_loss < 1_000_000:
        return AnnualLossBand.BETWEEN_50_100W
    if annual_loss < 3_000_000:
        return AnnualLossBand.BETWEEN_100_300W
    return AnnualLossBand.OVER_300W


def _decide_priority(answers: LeadAnswers) -> PriorityTier:
    """PRD §12.1 priority rules — one branch per ⭐ row."""
    if answers.current_method is CurrentMethod.SPECIALIZED_TOOL:
        return PriorityTier.SKIP
    if answers.decision_authority is DecisionAuthority.MULTI_PARTY:
        return PriorityTier.BRONZE
    if answers.current_method is CurrentMethod.WORKSHOP_EXPERIENCE:
        return PriorityTier.GOLD
    # excel and erp_report both indicate a single-director pain → SILVER
    return PriorityTier.SILVER


def assess_lead(answers: LeadAnswers) -> LeadAssessment:
    """Run the qualification rules from PRD §12.1 against one survey response."""
    # Resolve annual_loss + band — Q5 wins, Q6 fills in when Q5 is UNKNOWN.
    if answers.annual_loss_band is AnnualLossBand.UNKNOWN:
        if answers.monthly_loss_estimate_yuan is None:
            raise ValueError("monthly_loss_estimate_yuan is required when annual_loss_band=UNKNOWN")
        annual_loss = answers.monthly_loss_estimate_yuan * 12.0
        resolved_band = _infer_band_from_annual(annual_loss)
    else:
        annual_loss = _LOSS_ESTIMATE_BY_BAND[answers.annual_loss_band]
        resolved_band = answers.annual_loss_band

    fee = _FEE_BY_BAND[resolved_band]
    savings = annual_loss * _ADOPTION_RATE * _LOSS_REDUCTION_RATE
    roi = savings / fee if fee > 0 else 0.0

    return LeadAssessment(
        customer_name=answers.customer_name,
        industry=answers.industry,
        annual_loss_band=resolved_band,
        annual_loss_estimate_yuan=annual_loss,
        recommended_annual_fee_yuan=fee,
        estimated_annual_savings_yuan=savings,
        roi_multiple=roi,
        priority_tier=_decide_priority(answers),
        recommended_pilot_actions=[
            a.value for a in (*_ACTIONS_BY_INDUSTRY[answers.industry], ActionType.REPORT_LOSS)
        ],
        sales_pitch=_PITCH_BY_BAND[resolved_band],
        raw_answers=answers,
    )
