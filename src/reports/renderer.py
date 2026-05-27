"""PDF renderer: MonthlyReportData → bytes.

Why reportlab over weasyprint:
- Pure Python, no Cairo / Pango system dep — runs in any minimal Docker image.
- CID font STSong-Light ships with reportlab → Chinese works zero-config.

Layout intent: "总监 → 老板汇报材料" (PRD §5.5). Numbers should jump off the
page; explanation is secondary. We use 4 sections, each on its own page so the
PDF reads like a slide deck when printed.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.models import ActionType
from src.reports.aggregator import MonthlyReportData

_CHINESE_FONT = "STSong-Light"

_ACTION_LABEL: dict[ActionType, str] = {
    ActionType.TRANSFORM: "转加工",
    ActionType.DISCOUNT_CLEARANCE: "打折清仓",
    ActionType.EMPLOYEE_CANTEEN: "员工食堂消化",
    ActionType.TRANSFER_WAREHOUSE: "调拨分厂",
    ActionType.REPORT_LOSS: "报损",
}


def _register_font_once() -> None:
    if _CHINESE_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(_CHINESE_FONT))


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    # Build derived styles that all use the Chinese-capable CID font.
    title = ParagraphStyle(
        "ZhTitle",
        parent=base["Title"],
        fontName=_CHINESE_FONT,
        fontSize=28,
        leading=34,
        alignment=1,  # center
    )
    huge_number = ParagraphStyle(
        "ZhHuge",
        parent=base["Title"],
        fontName=_CHINESE_FONT,
        fontSize=48,
        leading=56,
        alignment=1,
        textColor=colors.HexColor("#0B5394"),
    )
    h2 = ParagraphStyle(
        "ZhH2",
        parent=base["Heading2"],
        fontName=_CHINESE_FONT,
        fontSize=18,
        leading=24,
        spaceAfter=12,
    )
    body = ParagraphStyle(
        "ZhBody",
        parent=base["BodyText"],
        fontName=_CHINESE_FONT,
        fontSize=11,
        leading=18,
    )
    callout = ParagraphStyle(
        "ZhCallout",
        parent=body,
        fontSize=13,
        leading=20,
        textColor=colors.HexColor("#0B5394"),
    )
    return {"title": title, "huge": huge_number, "h2": h2, "body": body, "callout": callout}


def _cover(data: MonthlyReportData, st: dict[str, ParagraphStyle]) -> list[Any]:
    return [
        Spacer(1, 3 * cm),
        Paragraph("Shelf-Life Copilot · 月度复盘", st["title"]),
        Spacer(1, 0.5 * cm),
        Paragraph(
            f"客户：{data.customer_id} · 行业：{data.industry} · 月份：{data.month}",
            st["body"],
        ),
        Spacer(1, 3 * cm),
        Paragraph("本月累计节省", st["h2"]),
        Paragraph(f"¥ {data.total_savings_actual:,.0f}", st["huge"]),
        Spacer(1, 0.8 * cm),
        Paragraph(
            f"AI 建议采纳 {data.approved_count} / {data.total_count} 次 "
            f"· 采纳率 {data.approval_rate:.0%} "
            f"· ROI {data.roi_multiple:.1f}×",
            st["callout"],
        ),
        PageBreak(),
    ]


def _adoption_section(data: MonthlyReportData, st: dict[str, ParagraphStyle]) -> list[Any]:
    rows = [
        ["指标", "数值"],
        ["总预警批次", f"{data.total_count}"],
        ["AI 建议被采纳", f"{data.approved_count}"],
        ["采纳率", f"{data.approval_rate:.0%}"],
        ["AI 估算累计节省", f"¥ {data.total_savings_estimate:,.0f}"],
        ["实际累计节省（已执行）", f"¥ {data.total_savings_actual:,.0f}"],
    ]
    table = Table(rows, colWidths=[8 * cm, 6 * cm])
    table.setStyle(_table_style())
    return [
        Paragraph("一、AI 建议采纳率", st["h2"]),
        table,
        Spacer(1, 0.6 * cm),
        Paragraph(
            "采纳率 = (同意 + 改方案后同意) / 总预警批次。改方案视为采纳，"
            "因为 AI 仍提供了决策路径，只是总监迭代到了更合适的方案。",
            st["body"],
        ),
        PageBreak(),
    ]


def _top_actions_section(data: MonthlyReportData, st: dict[str, ParagraphStyle]) -> list[Any]:
    rows: list[list[str]] = [["排名", "处置动作", "次数", "实际节省"]]
    for i, tally in enumerate(data.top_actions, start=1):
        rows.append(
            [
                str(i),
                _ACTION_LABEL.get(tally.action, tally.action.value),
                str(tally.approved_count),
                f"¥ {tally.total_actual_savings:,.0f}",
            ]
        )
    if len(rows) == 1:
        rows.append(["—", "（本月无已执行的处置）", "—", "—"])
    table = Table(rows, colWidths=[1.5 * cm, 6 * cm, 2.5 * cm, 4 * cm])
    table.setStyle(_table_style())
    return [
        Paragraph("二、Top 5 高频处置类型", st["h2"]),
        table,
        PageBreak(),
    ]


def _case_studies_section(data: MonthlyReportData, st: dict[str, ParagraphStyle]) -> list[Any]:
    elements: list[Any] = [Paragraph("三、典型决策案例", st["h2"])]
    if not data.case_studies:
        elements.append(
            Paragraph(
                "（本月无已执行决策可作为案例。下月数据进入后将自动填充。）",
                st["body"],
            )
        )
        elements.append(PageBreak())
        return elements

    for i, d in enumerate(data.case_studies, start=1):
        date_str = d.decided_at.date().isoformat()
        action_label = _ACTION_LABEL.get(d.action, d.action.value)
        body = (
            f"<b>案例 {i} · {d.material_name}</b><br/>"
            f"批次：{d.batch_id} · 决策日期：{date_str} · 动作：{action_label}<br/>"
            f"预估节省：¥{d.savings_estimate:,.0f} · 实际节省：¥{(d.actual_savings or 0):,.0f} · "
            f"实际处置量：{(d.actual_qty or 0):,.0f}"
        )
        elements.append(Paragraph(body, st["body"]))
        if d.notes:
            elements.append(Paragraph(f"<i>备注：{d.notes}</i>", st["body"]))
        elements.append(Spacer(1, 0.5 * cm))
    elements.append(PageBreak())
    return elements


def _roi_section(data: MonthlyReportData, st: dict[str, ParagraphStyle]) -> list[Any]:
    annualized_savings = data.total_savings_actual * 12
    reduction_rate = (
        (annualized_savings / data.annual_baseline_loss) if data.annual_baseline_loss else 0.0
    )
    rows = [
        ["项", "金额"],
        ["年度报损 baseline", f"¥ {data.annual_baseline_loss:,.0f}"],
        ["本月 AI 投入（按 v1.0 分档年费摊月）", f"¥ {data.monthly_subscription_fee:,.0f}"],
        ["本月实际节省", f"¥ {data.total_savings_actual:,.0f}"],
        ["按本月年化节省（×12）", f"¥ {annualized_savings:,.0f}"],
        ["年度报损降幅（年化估算）", f"{reduction_rate:.0%}"],
        ["本月 ROI 倍数（实际节省 / AI 投入）", f"{data.roi_multiple:.1f}×"],
    ]
    table = Table(rows, colWidths=[10 * cm, 5 * cm])
    table.setStyle(_table_style())
    return [
        Paragraph("四、ROI 测算", st["h2"]),
        table,
        Spacer(1, 0.6 * cm),
        Paragraph(
            "<i>ROI 倍数 = 本月实际节省 / 本月 AI 投入。年度报损降幅按当月节省年化估算，"
            "实际全年情况以 12 个月数据为准。</i>",
            st["body"],
        ),
    ]


def _table_style() -> TableStyle:
    return TableStyle(
        [
            ("FONTNAME", (0, 0), (-1, -1), _CHINESE_FONT),
            ("FONTSIZE", (0, 0), (-1, -1), 11),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B5394")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]
    )


def render_monthly_report_pdf(data: MonthlyReportData) -> bytes:
    """Render one MonthlyReportData into a PDF byte stream."""
    _register_font_once()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=f"Shelf-Life Copilot 月报 · {data.customer_id} · {data.month}",
        author="Shelf-Life Copilot",
    )
    st = _styles()
    story: list[Any] = []
    story.extend(_cover(data, st))
    story.extend(_adoption_section(data, st))
    story.extend(_top_actions_section(data, st))
    story.extend(_case_studies_section(data, st))
    story.extend(_roi_section(data, st))
    doc.build(story)
    return buf.getvalue()
