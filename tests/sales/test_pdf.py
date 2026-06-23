"""ROI 一页纸 PDF tests — parse with pypdf and assert key fields landed."""

from __future__ import annotations

from io import BytesIO

import pypdf

from src.sales import (
    AnnualLossBand,
    CurrentMethod,
    DecisionAuthority,
    IndustryCategory,
    LeadAnswers,
    assess_lead,
)
from src.sales.pdf import ContactInfo, render_lead_pdf


def _customer_a_assessment() -> object:
    return assess_lead(
        LeadAnswers(
            customer_name="客户A · 冷冻食品厂",
            industry=IndustryCategory.FROZEN_RAW,
            annual_procurement_band="1-5亿",
            sku_count_band="200-1000",
            avg_shelf_life_band="30-90天",
            annual_loss_band=AnnualLossBand.BETWEEN_100_300W,
            current_method=CurrentMethod.WORKSHOP_EXPERIENCE,
            decision_authority=DecisionAuthority.SUPPLY_CHAIN_DIRECTOR,
        )
    )


def _extract_text(pdf_bytes: bytes) -> str:
    reader = pypdf.PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


class TestSeparatorGlyph:
    """STSong-Light lacks U+00B7 (·) → tofu (□). We sanitize it to U+30FB (・),
    covering both hardcoded separators and a customer name that contains '·'
    (the fixture's customer_name does)."""

    def test_no_tofu_middle_dot(self) -> None:
        text = _extract_text(render_lead_pdf(_customer_a_assessment()))
        assert "·" not in text

    def test_uses_katakana_middle_dot(self) -> None:
        text = _extract_text(render_lead_pdf(_customer_a_assessment()))
        assert "・" in text


class TestRenderLeadPdf:
    def test_returns_bytes_starting_with_pdf_magic(self) -> None:
        pdf = render_lead_pdf(_customer_a_assessment())
        assert isinstance(pdf, bytes)
        assert pdf.startswith(b"%PDF")

    def test_single_page(self) -> None:
        pdf = render_lead_pdf(_customer_a_assessment())
        reader = pypdf.PdfReader(BytesIO(pdf))
        assert len(reader.pages) == 1

    def test_contains_customer_name(self) -> None:
        pdf = render_lead_pdf(_customer_a_assessment())
        assert "客户A" in _extract_text(pdf)

    def test_contains_kpi_numbers(self) -> None:
        pdf = render_lead_pdf(_customer_a_assessment())
        text = _extract_text(pdf)
        # 年损 200 万 (估算) — pypdf 不一定保留逗号格式，做宽松匹配
        assert "2,000,000" in text or "2000000" in text
        # 年节省 36 万
        assert "360,000" in text or "360000" in text
        # 年费 15 万
        assert "150,000" in text or "150000" in text
        # ROI 2.4×
        assert "2.4" in text

    def test_contains_recommended_actions(self) -> None:
        pdf = render_lead_pdf(_customer_a_assessment())
        text = _extract_text(pdf)
        # 中文动作 label（renderer 把 enum value 换成中文短语，跟月度 PDF 一致）
        assert "转加工" in text
        assert "打折清仓" in text
        assert "报损" in text

    def test_contains_sales_pitch(self) -> None:
        pdf = render_lead_pdf(_customer_a_assessment())
        # PRD §12.1 pitch — 含"3 个月免费"和"试点"
        text = _extract_text(pdf)
        assert "3" in text and "免费" in text
        assert "试点" in text

    def test_no_emoji_in_pdf_text(self) -> None:
        """STSong-Light is a CID font that lacks emoji glyphs; using emoji in
        bullets caused PDFs to render mojibake (e.g. 䰀 instead of ❌). All
        button-name references must use Chinese brackets like 「同意」."""
        import re

        pdf = render_lead_pdf(_customer_a_assessment())
        text = _extract_text(pdf)
        # Common offenders we previously shipped.
        for ch in ("✅", "❌", "💬", "📋", "🚨", "⭐"):
            assert ch not in text, f"emoji {ch!r} leaked into PDF text"
        # Catch any other emoji/symbol-plane characters that might creep in.
        emoji_pattern = re.compile(r"[\U0001F000-\U0001FFFF☀-➿]")
        offenders = emoji_pattern.findall(text)
        assert offenders == [], f"unexpected emoji in PDF: {offenders}"

    def test_button_names_use_chinese_brackets(self) -> None:
        pdf = render_lead_pdf(_customer_a_assessment())
        text = _extract_text(pdf)
        # The "为什么值得试点" block names the three buttons by 中文 instead of emoji.
        assert "同意" in text and "稍后" in text and "改方案" in text

    def test_contact_info_embedded_when_given(self) -> None:
        contact = ContactInfo(name="王销售", phone="13800138000", email="wang@example.com")
        pdf = render_lead_pdf(_customer_a_assessment(), contact=contact)
        text = _extract_text(pdf)
        assert "王销售" in text
        assert "13800138000" in text
        assert "wang@example.com" in text

    def test_contact_with_only_name_renders(self) -> None:
        """Phone / email optional — name-only contact should still print cleanly."""
        contact = ContactInfo(name="李销售")
        pdf = render_lead_pdf(_customer_a_assessment(), contact=contact)
        text = _extract_text(pdf)
        assert "李销售" in text
        # No phone / email lines should be added.
        assert "电话" not in text
        assert "邮箱" not in text

    def test_missing_contact_renders_placeholder(self) -> None:
        pdf = render_lead_pdf(_customer_a_assessment())
        text = _extract_text(pdf)
        # Without ContactInfo, a placeholder line still appears so sales sees
        # where their name should go after the customer gets their copy.
        assert "联系" in text


class TestEdgeCases:
    def test_handles_under_50w_band_negative_roi_gracefully(self) -> None:
        """ROI < 1.0 (under-50w band) — PDF should still render without crashing."""
        small = assess_lead(
            LeadAnswers(
                customer_name="客户测试",
                industry=IndustryCategory.SNACKS,
                annual_procurement_band="< 1亿",
                sku_count_band="< 200",
                avg_shelf_life_band="> 1年",
                annual_loss_band=AnnualLossBand.UNDER_50W,
                current_method=CurrentMethod.EXCEL,
                decision_authority=DecisionAuthority.OWNER,
            )
        )
        pdf = render_lead_pdf(small)
        assert pdf.startswith(b"%PDF")
        text = _extract_text(pdf)
        # Honest reporting: should still show the ROI value even when < 1
        assert "0.7" in text  # 0.675 → 0.7×

    def test_over_300w_band_renders(self) -> None:
        big = assess_lead(
            LeadAnswers(
                customer_name="大客户",
                industry=IndustryCategory.READY_MEAL,
                annual_procurement_band="> 20亿",
                sku_count_band="> 5000",
                avg_shelf_life_band="30-90天",
                annual_loss_band=AnnualLossBand.OVER_300W,
                current_method=CurrentMethod.WORKSHOP_EXPERIENCE,
                decision_authority=DecisionAuthority.OWNER,
            )
        )
        pdf = render_lead_pdf(big)
        text = _extract_text(pdf)
        # 议价起步 25 万 should appear (sales pitch text)
        assert "议价" in text or "25" in text
