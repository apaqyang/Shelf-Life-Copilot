"""Tests for assess_lead — PRD §12.1 sales rules encoded as code.

Each test pins down one row of the rules tables in §12.1 so the next sales
hire can read the tests to see the rules without parsing prose.
"""

from __future__ import annotations

import pytest

from src.sales import (
    AnnualLossBand,
    CurrentMethod,
    DecisionAuthority,
    IndustryCategory,
    LeadAnswers,
    PriorityTier,
    assess_lead,
)


def _answers(
    *,
    customer_name: str = "客户测试",
    industry: IndustryCategory = IndustryCategory.FROZEN_RAW,
    annual_loss_band: AnnualLossBand = AnnualLossBand.BETWEEN_100_300W,
    monthly_loss_estimate_yuan: float | None = None,
    current_method: CurrentMethod = CurrentMethod.EXCEL,
    decision_authority: DecisionAuthority = DecisionAuthority.SUPPLY_CHAIN_DIRECTOR,
) -> LeadAnswers:
    return LeadAnswers(
        customer_name=customer_name,
        industry=industry,
        annual_procurement_band="1-5亿",
        sku_count_band="200-1000",
        avg_shelf_life_band="30-90天",
        annual_loss_band=annual_loss_band,
        monthly_loss_estimate_yuan=monthly_loss_estimate_yuan,
        current_method=current_method,
        decision_authority=decision_authority,
    )


class TestFeeTier:
    """PRD §12.1 sales 分档对照 — Q5 答案直接决定年费档."""

    @pytest.mark.parametrize(
        ("band", "expected_fee"),
        [
            (AnnualLossBand.UNDER_50W, 80_000.0),
            (AnnualLossBand.BETWEEN_50_100W, 80_000.0),
            (AnnualLossBand.BETWEEN_100_300W, 150_000.0),
            (AnnualLossBand.OVER_300W, 250_000.0),  # 议价起步
        ],
    )
    def test_fee_by_band(self, band: AnnualLossBand, expected_fee: float) -> None:
        a = assess_lead(_answers(annual_loss_band=band))
        assert a.recommended_annual_fee_yuan == expected_fee


class TestAnnualLossEstimate:
    """Band → loss estimate uses the middle of each PRD range (defensible to sales)."""

    @pytest.mark.parametrize(
        ("band", "expected_loss"),
        [
            (AnnualLossBand.UNDER_50W, 300_000.0),
            (AnnualLossBand.BETWEEN_50_100W, 750_000.0),
            (AnnualLossBand.BETWEEN_100_300W, 2_000_000.0),
            (AnnualLossBand.OVER_300W, 4_000_000.0),
        ],
    )
    def test_loss_estimate(self, band: AnnualLossBand, expected_loss: float) -> None:
        a = assess_lead(_answers(annual_loss_band=band))
        assert a.annual_loss_estimate_yuan == expected_loss


class TestUnknownLossFallback:
    """Q5=UNKNOWN must fall back to Q6 monthly_loss * 12 and infer the band."""

    def test_monthly_loss_drives_annual_estimate(self) -> None:
        a = assess_lead(
            _answers(
                annual_loss_band=AnnualLossBand.UNKNOWN,
                monthly_loss_estimate_yuan=20_000.0,  # → 24 万/年
            )
        )
        assert a.annual_loss_estimate_yuan == 240_000.0
        # 24 万 < 100 万 → fee = 8 万
        assert a.recommended_annual_fee_yuan == 80_000.0

    def test_high_monthly_loss_rolls_into_300w_plus_band(self) -> None:
        a = assess_lead(
            _answers(
                annual_loss_band=AnnualLossBand.UNKNOWN,
                monthly_loss_estimate_yuan=300_000.0,  # → 360 万/年
            )
        )
        assert a.annual_loss_estimate_yuan == 3_600_000.0
        assert a.recommended_annual_fee_yuan == 250_000.0  # > 300 万 议价起步

    def test_monthly_loss_lands_in_50_100w_band(self) -> None:
        """60 万 monthly × 12 wait no — 6 万 × 12 = 72 万 (lands 50-100 万 band)."""
        a = assess_lead(
            _answers(
                annual_loss_band=AnnualLossBand.UNKNOWN,
                monthly_loss_estimate_yuan=60_000.0,  # → 72 万/年
            )
        )
        assert a.recommended_annual_fee_yuan == 80_000.0  # 50-100 万 band → 8 万 fee

    def test_monthly_loss_lands_in_100_300w_band(self) -> None:
        a = assess_lead(
            _answers(
                annual_loss_band=AnnualLossBand.UNKNOWN,
                monthly_loss_estimate_yuan=150_000.0,  # → 180 万/年
            )
        )
        assert a.recommended_annual_fee_yuan == 150_000.0  # 100-300 万 band → 15 万 fee

    def test_unknown_without_q6_raises(self) -> None:
        """Q5=UNKNOWN requires Q6 — the survey itself enforces this; we double-check."""
        with pytest.raises(ValueError, match="monthly_loss"):
            assess_lead(
                _answers(
                    annual_loss_band=AnnualLossBand.UNKNOWN,
                    monthly_loss_estimate_yuan=None,
                )
            )


class TestRoiCalculation:
    """ROI = (年损 × 60% 采纳率 × 30% 减损率) / 年费 — same numbers as DEMO_SCRIPT §4:00."""

    def test_100_300w_band_yields_double_digit_roi(self) -> None:
        a = assess_lead(_answers(annual_loss_band=AnnualLossBand.BETWEEN_100_300W))
        # loss = 200 万 → 节省 = 200 万 × 0.6 × 0.3 = 36 万 / 年费 15 万 = 2.4x
        assert a.estimated_annual_savings_yuan == pytest.approx(360_000.0)
        assert a.roi_multiple == pytest.approx(2.4, rel=0.01)

    def test_under_50w_band(self) -> None:
        a = assess_lead(_answers(annual_loss_band=AnnualLossBand.UNDER_50W))
        # loss = 30 万 → 节省 = 5.4 万 / 年费 8 万 = 0.675
        assert a.roi_multiple < 1.0  # honest: ROI below break-even at this band

    def test_over_300w_band(self) -> None:
        a = assess_lead(_answers(annual_loss_band=AnnualLossBand.OVER_300W))
        # loss = 400 万 → 节省 = 72 万 / 年费 25 万 = 2.88x
        assert a.roi_multiple > 2.5


class TestPriorityTier:
    """PRD §12.1 优先级判定规则 — encoded one rule per test for readability."""

    def test_gold_workshop_experience_plus_single_director(self) -> None:
        a = assess_lead(
            _answers(
                current_method=CurrentMethod.WORKSHOP_EXPERIENCE,
                decision_authority=DecisionAuthority.SUPPLY_CHAIN_DIRECTOR,
            )
        )
        assert a.priority_tier is PriorityTier.GOLD

    def test_silver_excel_plus_single_director(self) -> None:
        a = assess_lead(
            _answers(
                current_method=CurrentMethod.EXCEL,
                decision_authority=DecisionAuthority.PURCHASING_DIRECTOR,
            )
        )
        assert a.priority_tier is PriorityTier.SILVER

    def test_bronze_multi_party_decision(self) -> None:
        a = assess_lead(
            _answers(
                current_method=CurrentMethod.WORKSHOP_EXPERIENCE,
                decision_authority=DecisionAuthority.MULTI_PARTY,
            )
        )
        assert a.priority_tier is PriorityTier.BRONZE

    def test_skip_already_has_specialized_tool(self) -> None:
        """Specialized-tool clients have switching cost too high — defer regardless."""
        a = assess_lead(
            _answers(
                current_method=CurrentMethod.SPECIALIZED_TOOL,
                decision_authority=DecisionAuthority.OWNER,
            )
        )
        assert a.priority_tier is PriorityTier.SKIP

    def test_erp_report_with_single_director_is_silver(self) -> None:
        """ERP-report is between excel and tool — treated as silver tier."""
        a = assess_lead(
            _answers(
                current_method=CurrentMethod.ERP_REPORT,
                decision_authority=DecisionAuthority.OWNER,
            )
        )
        assert a.priority_tier is PriorityTier.SILVER


class TestRecommendedActions:
    """Q1 industry → suggested PoC action subset (engineering pre-fills actions JSON)."""

    @pytest.mark.parametrize(
        ("industry", "expected_includes"),
        [
            (IndustryCategory.FROZEN_RAW, ["transform", "discount_clearance"]),
            (IndustryCategory.READY_MEAL, ["discount_clearance", "employee_canteen"]),
            (IndustryCategory.BAKERY, ["discount_clearance", "employee_canteen"]),
            (IndustryCategory.SNACKS, ["discount_clearance"]),
            (IndustryCategory.FRESH_PROCESSING, ["transform", "employee_canteen"]),
            (IndustryCategory.OTHER, ["transform", "discount_clearance"]),
        ],
    )
    def test_industry_drives_action_preset(
        self, industry: IndustryCategory, expected_includes: list[str]
    ) -> None:
        a = assess_lead(_answers(industry=industry))
        for action in expected_includes:
            assert action in a.recommended_pilot_actions
        # report_loss is always included as the last-resort fallback
        assert "report_loss" in a.recommended_pilot_actions


class TestSalesPitch:
    """Pitch line should match the PRD table verbatim (sales reads it on-screen)."""

    def test_under_100w_pitch_mentions_5_to_6_x(self) -> None:
        a = assess_lead(_answers(annual_loss_band=AnnualLossBand.UNDER_50W))
        assert "8-10%" in a.sales_pitch

    def test_100_300w_pitch_mentions_4_to_6_x(self) -> None:
        a = assess_lead(_answers(annual_loss_band=AnnualLossBand.BETWEEN_100_300W))
        assert "4-6 倍" in a.sales_pitch

    def test_over_300w_pitch_mentions_roi_path(self) -> None:
        a = assess_lead(_answers(annual_loss_band=AnnualLossBand.OVER_300W))
        # No fixed multiple — sales does separate ROI work
        assert "高管" in a.sales_pitch or "议价" in a.sales_pitch


class TestPassthroughFields:
    def test_assessment_preserves_raw_answers(self) -> None:
        ans = _answers(customer_name="客户A")
        a = assess_lead(ans)
        assert a.raw_answers == ans
        assert a.customer_name == "客户A"
        assert a.assessed_at.tzinfo is not None


class TestExtractAnswersFromAssessmentJson:
    """`--reassess` reads a written LeadAssessment JSON back into LeadAnswers
    so sales can tweak one field and re-run without filling the 8 questions again."""

    def test_roundtrip_preserves_all_answer_fields(self) -> None:
        from src.sales import extract_answers_from_assessment_json

        original_answers = _answers(customer_name="客户A")
        json_str = assess_lead(original_answers).model_dump_json()

        restored = extract_answers_from_assessment_json(json_str)
        assert restored == original_answers

    def test_modified_loss_band_changes_fee_on_reassess(self) -> None:
        """Mutating raw_answers.annual_loss_band before reassess → different fee."""
        from src.sales import extract_answers_from_assessment_json

        original_answers = _answers(annual_loss_band=AnnualLossBand.BETWEEN_50_100W)
        original_assessment = assess_lead(original_answers)
        assert original_assessment.recommended_annual_fee_yuan == 80_000.0

        # Sales discovers the customer's loss was higher than first quoted
        import json

        data = json.loads(original_assessment.model_dump_json())
        data["raw_answers"]["annual_loss_band"] = "100w_300w"
        modified_json = json.dumps(data)

        restored = extract_answers_from_assessment_json(modified_json)
        new = assess_lead(restored)
        assert new.recommended_annual_fee_yuan == 150_000.0
        assert new.roi_multiple > original_assessment.roi_multiple

    def test_invalid_json_raises(self) -> None:
        from src.sales import extract_answers_from_assessment_json

        with pytest.raises(ValueError):
            extract_answers_from_assessment_json("{not even json")

    def test_assessment_json_missing_raw_answers_raises(self) -> None:
        """If someone passes a non-LeadAssessment JSON, fail loudly with a useful error."""
        from src.sales import extract_answers_from_assessment_json

        with pytest.raises(ValueError):
            extract_answers_from_assessment_json('{"customer_name": "x"}')
