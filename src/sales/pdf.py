"""ROI 一页纸 PDF — what sales prints / emails / hands to the director.

One A4 page, four big KPI cells up top, a "why试点" persuasion block in the
middle, recommended PoC actions, and the sales rep's contact line at the
bottom. The whole point is "look at this for 30 seconds and decide whether
to take the next meeting" — anything that doesn't move that needle stays off.

Font: STSong-Light CID, same as the monthly report (zero system deps).
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from pydantic import BaseModel, ConfigDict
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.models import ActionType
from src.sales.models import IndustryCategory, LeadAssessment

_CHINESE_FONT = "STSong-Light"

# Chinese display labels — mirrors src/reports/renderer.py for consistency
_ACTION_LABEL: dict[str, str] = {
    ActionType.TRANSFORM.value: "转加工",
    ActionType.DISCOUNT_CLEARANCE.value: "打折清仓",
    ActionType.EMPLOYEE_CANTEEN.value: "员工食堂消化",
    ActionType.TRANSFER_WAREHOUSE.value: "调拨分厂",
    ActionType.REPORT_LOSS.value: "报损",
}

_INDUSTRY_LABEL: dict[IndustryCategory, str] = {
    IndustryCategory.FROZEN_RAW: "冷冻原料",
    IndustryCategory.READY_MEAL: "预制菜",
    IndustryCategory.BAKERY: "烘焙",
    IndustryCategory.SNACKS: "休闲食品",
    IndustryCategory.FRESH_PROCESSING: "生鲜加工",
    IndustryCategory.OTHER: "其他食品",
}


class ContactInfo(BaseModel):
    """Sales rep contact card printed at the bottom of the one-pager."""

    model_config = ConfigDict(frozen=True)

    name: str
    phone: str | None = None
    email: str | None = None
    title: str = "客户经理"


def _register_font_once() -> None:
    # reportlab's registerFont is idempotent (last-write-wins), so we skip the
    # "already registered?" check that bloats branch coverage for no benefit.
    pdfmetrics.registerFont(UnicodeCIDFont(_CHINESE_FONT))


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    title = ParagraphStyle(
        "ZhTitle",
        parent=base["Title"],
        fontName=_CHINESE_FONT,
        fontSize=20,
        leading=24,
        alignment=1,
    )
    subtitle = ParagraphStyle(
        "ZhSubtitle",
        parent=base["BodyText"],
        fontName=_CHINESE_FONT,
        fontSize=11,
        leading=15,
        alignment=1,
        textColor=colors.HexColor("#555555"),
    )
    h2 = ParagraphStyle(
        "ZhH2",
        parent=base["Heading2"],
        fontName=_CHINESE_FONT,
        fontSize=13,
        leading=17,
        spaceBefore=10,
        spaceAfter=6,
        textColor=colors.HexColor("#0B5394"),
    )
    body = ParagraphStyle(
        "ZhBody",
        parent=base["BodyText"],
        fontName=_CHINESE_FONT,
        fontSize=10,
        leading=15,
    )
    footnote = ParagraphStyle(
        "ZhFootnote",
        parent=body,
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#888888"),
    )
    kpi_label = ParagraphStyle(
        "ZhKpiLabel",
        parent=base["BodyText"],
        fontName=_CHINESE_FONT,
        fontSize=10,
        leading=13,
        alignment=1,
        textColor=colors.HexColor("#555555"),
    )
    kpi_value = ParagraphStyle(
        "ZhKpiValue",
        parent=base["Title"],
        fontName=_CHINESE_FONT,
        fontSize=18,
        leading=22,
        alignment=1,
        textColor=colors.HexColor("#0B5394"),
    )
    return {
        "title": title,
        "subtitle": subtitle,
        "h2": h2,
        "body": body,
        "footnote": footnote,
        "kpi_label": kpi_label,
        "kpi_value": kpi_value,
    }


def _kpi_block(assessment: LeadAssessment, st: dict[str, ParagraphStyle]) -> Table:
    """4-cell KPI row: 年损 / 年节省 / 年费 / ROI."""
    cells = [
        [
            Paragraph("年损（估算）", st["kpi_label"]),
            Paragraph("年节省（预测）", st["kpi_label"]),
            Paragraph("年费（推荐）", st["kpi_label"]),
            Paragraph("ROI", st["kpi_label"]),
        ],
        [
            Paragraph(f"¥{assessment.annual_loss_estimate_yuan:,.0f}", st["kpi_value"]),
            Paragraph(f"¥{assessment.estimated_annual_savings_yuan:,.0f}", st["kpi_value"]),
            Paragraph(f"¥{assessment.recommended_annual_fee_yuan:,.0f}", st["kpi_value"]),
            Paragraph(f"{assessment.roi_multiple:.1f}×", st["kpi_value"]),
        ],
    ]
    table = Table(cells, colWidths=[4.2 * cm] * 4, rowHeights=[1 * cm, 1.4 * cm])
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#EEEEEE")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _why_pilot_block(st: dict[str, ParagraphStyle]) -> list[Any]:
    bullets = [
        "每天 07:00 自动推送临期预警 + AI 处置建议到您手机企微",
        "您一键 ✅ 同意 / ❌ 稍后 / 💬 改方案 — 总监决策 1 秒完成",
        "✅ 同意自动派单到车间，全程留决策日志可审计",
        "3 个月后给您完整数据看板：节省总额、ROI、最佳动作 — 看不到效果可退",
    ]
    return [
        Paragraph("▎为什么值得 3 个月免费试点？", st["h2"]),
        *[Paragraph(f"• {b}", st["body"]) for b in bullets],
    ]


def _actions_block(assessment: LeadAssessment, st: dict[str, ParagraphStyle]) -> list[Any]:
    items = [f"• {_ACTION_LABEL.get(a, a)}" for a in assessment.recommended_pilot_actions]
    return [
        Paragraph("▎PoC 阶段建议启用动作（按贵司行业匹配）", st["h2"]),
        *[Paragraph(t, st["body"]) for t in items],
    ]


def _pitch_block(assessment: LeadAssessment, st: dict[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(
        f"▎销售一句话：{assessment.sales_pitch}",
        st["body"],
    )


def _contact_block(contact: ContactInfo | None, st: dict[str, ParagraphStyle]) -> list[Any]:
    if contact is None:
        return [
            Paragraph("▎联系方式", st["h2"]),
            Paragraph("（销售代表姓名 / 电话 / 邮箱 — 见纸质版手填）", st["body"]),
        ]
    lines = [f"{contact.title} {contact.name}"]
    if contact.phone:
        lines.append(f"电话：{contact.phone}")
    if contact.email:
        lines.append(f"邮箱：{contact.email}")
    return [
        Paragraph("▎联系方式", st["h2"]),
        Paragraph(" · ".join(lines), st["body"]),
    ]


def _footer_block(st: dict[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(
        "评估方法：年损中位数估算 × 60% 采纳率 × 30% 减损率。"
        "实际效果以 PoC 阶段真实决策日志为准。"
        "本表由 Shelf-Life Copilot 自动生成（PRD §12.1）。",
        st["footnote"],
    )


def render_lead_pdf(
    assessment: LeadAssessment,
    contact: ContactInfo | None = None,
) -> bytes:
    """Render the ROI one-pager. Returns raw PDF bytes — caller decides where to write."""
    _register_font_once()
    st = _styles()
    industry_label = _INDUSTRY_LABEL.get(assessment.industry, assessment.industry.value)

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=1.6 * cm,
        bottomMargin=1.6 * cm,
        title=f"ROI 评估 · {assessment.customer_name}",
        author="Shelf-Life Copilot",
    )

    story: list[Any] = [
        Paragraph("Shelf-Life Copilot · ROI 评估", st["title"]),
        Paragraph(
            f"客户：{assessment.customer_name} · 行业：{industry_label} · "
            f"评估日期：{assessment.assessed_at.strftime('%Y-%m-%d')}",
            st["subtitle"],
        ),
        Spacer(1, 0.5 * cm),
        _kpi_block(assessment, st),
        Spacer(1, 0.3 * cm),
        _pitch_block(assessment, st),
        Spacer(1, 0.2 * cm),
        *_why_pilot_block(st),
        Spacer(1, 0.2 * cm),
        *_actions_block(assessment, st),
        Spacer(1, 0.2 * cm),
        *_contact_block(contact, st),
        Spacer(1, 0.3 * cm),
        _footer_block(st),
    ]

    doc.build(story)
    return buf.getvalue()
