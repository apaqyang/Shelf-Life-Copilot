"""Tests for render_assessment_markdown — pin key sections without over-specifying."""

from __future__ import annotations

from src.sales import (
    AnnualLossBand,
    CurrentMethod,
    DecisionAuthority,
    IndustryCategory,
    LeadAnswers,
    assess_lead,
)
from src.sales.report import render_assessment_markdown


def _answers() -> LeadAnswers:
    return LeadAnswers(
        customer_name="客户A · 冷冻食品厂",
        industry=IndustryCategory.FROZEN_RAW,
        annual_procurement_band="1-5亿",
        sku_count_band="200-1000",
        avg_shelf_life_band="30-90天",
        annual_loss_band=AnnualLossBand.BETWEEN_100_300W,
        monthly_loss_estimate_yuan=None,
        current_method=CurrentMethod.WORKSHOP_EXPERIENCE,
        decision_authority=DecisionAuthority.SUPPLY_CHAIN_DIRECTOR,
    )


class TestRenderAssessmentMarkdown:
    def test_contains_customer_name_in_heading(self) -> None:
        md = render_assessment_markdown(assess_lead(_answers()))
        assert "客户A · 冷冻食品厂" in md

    def test_contains_priority_label_gold(self) -> None:
        md = render_assessment_markdown(assess_lead(_answers()))
        assert "⭐⭐⭐" in md

    def test_contains_recommended_fee_and_roi(self) -> None:
        md = render_assessment_markdown(assess_lead(_answers()))
        assert "150,000" in md  # 15 万年费
        assert "2.4x" in md  # ROI 2.4x

    def test_lists_actions_block(self) -> None:
        md = render_assessment_markdown(assess_lead(_answers()))
        assert "transform" in md
        assert "discount_clearance" in md
        assert "report_loss" in md  # always-included fallback

    def test_includes_section_headers(self) -> None:
        md = render_assessment_markdown(assess_lead(_answers()))
        assert "## 一、关键结论" in md
        assert "## 二、客户画像" in md
        assert "## 三、PoC 建议启用动作" in md
        assert "## 四、下一步" in md
