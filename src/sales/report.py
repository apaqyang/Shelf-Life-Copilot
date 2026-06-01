"""Render a LeadAssessment into a human-readable markdown report.

Lives in `src/` (not `tools/`) because the rendering logic is part of the sales
data contract — same prose every time, no surprises for the customer.
"""

from __future__ import annotations

from src.sales.models import (
    AnnualLossBand,
    CurrentMethod,
    DecisionAuthority,
    IndustryCategory,
    LeadAssessment,
    PriorityTier,
)

_INDUSTRY_LABEL: dict[IndustryCategory, str] = {
    IndustryCategory.FROZEN_RAW: "冷冻原料",
    IndustryCategory.READY_MEAL: "预制菜",
    IndustryCategory.BAKERY: "烘焙",
    IndustryCategory.SNACKS: "休闲食品",
    IndustryCategory.FRESH_PROCESSING: "生鲜加工",
    IndustryCategory.OTHER: "其他",
}

_BAND_LABEL: dict[AnnualLossBand, str] = {
    AnnualLossBand.UNDER_50W: "< 50 万",
    AnnualLossBand.BETWEEN_50_100W: "50-100 万",
    AnnualLossBand.BETWEEN_100_300W: "100-300 万",
    AnnualLossBand.OVER_300W: "> 300 万",
    AnnualLossBand.UNKNOWN: "未知（Q6 兜底）",
}

_METHOD_LABEL: dict[CurrentMethod, str] = {
    CurrentMethod.WORKSHOP_EXPERIENCE: "完全凭车间经验",
    CurrentMethod.EXCEL: "人工 Excel",
    CurrentMethod.ERP_REPORT: "ERP 报表",
    CurrentMethod.SPECIALIZED_TOOL: "已有专门工具",
}

_AUTHORITY_LABEL: dict[DecisionAuthority, str] = {
    DecisionAuthority.SUPPLY_CHAIN_DIRECTOR: "供应链总监",
    DecisionAuthority.PURCHASING_DIRECTOR: "采购总监",
    DecisionAuthority.PRODUCTION_DIRECTOR: "生产总监",
    DecisionAuthority.OWNER: "老板亲自",
    DecisionAuthority.MULTI_PARTY: "多人会签",
}

_PRIORITY_LABEL: dict[PriorityTier, str] = {
    PriorityTier.GOLD: "⭐⭐⭐ 优先排进 PoC",
    PriorityTier.SILVER: "⭐⭐ 适合 PoC",
    PriorityTier.BRONZE: "⭐ 谨慎评估",
    PriorityTier.SKIP: "❌ 暂缓",
}


def render_assessment_markdown(assessment: LeadAssessment) -> str:
    """One-screen markdown summary — sales sees it on terminal, also goes into JSON record."""
    a = assessment
    ans = a.raw_answers
    actions_block = "\n".join(f"- {act}" for act in a.recommended_pilot_actions)

    return (
        f"# 销售线索评估 · {a.customer_name}\n"
        f"\n"
        f"_评估时间：{a.assessed_at.isoformat(timespec='seconds')}_\n"
        f"\n"
        f"## 一、关键结论\n"
        f"\n"
        f"| 项 | 值 |\n"
        f"|---|---|\n"
        f"| **优先级** | {_PRIORITY_LABEL[a.priority_tier]} |\n"
        f"| **年损档位** | {_BAND_LABEL[a.annual_loss_band]} (估算 ¥{a.annual_loss_estimate_yuan:,.0f}) |\n"
        f"| **推荐年费** | **¥{a.recommended_annual_fee_yuan:,.0f} / 年** |\n"
        f"| **预测年节省** | ¥{a.estimated_annual_savings_yuan:,.0f} (年损 × 60% 采纳 × 30% 减损) |\n"
        f"| **ROI** | **{a.roi_multiple:.1f}x** 年费 |\n"
        f"| **销售话术** | {a.sales_pitch} |\n"
        f"\n"
        f"## 二、客户画像（来自问卷）\n"
        f"\n"
        f"| # | 题目 | 答案 |\n"
        f"|---|---|---|\n"
        f"| Q1 | 主营品类 | {_INDUSTRY_LABEL[ans.industry]} |\n"
        f"| Q2 | 年采购总额 | {ans.annual_procurement_band} |\n"
        f"| Q3 | SKU 数 | {ans.sku_count_band} |\n"
        f"| Q4 | 平均保质期 | {ans.avg_shelf_life_band} |\n"
        f"| Q5 | 去年报损金额 | {_BAND_LABEL[ans.annual_loss_band]} |\n"
        f"| Q6 | 月损估算（仅 Q5=未知 时） | "
        f"{f'¥{ans.monthly_loss_estimate_yuan:,.0f}' if ans.monthly_loss_estimate_yuan else '—'} |\n"
        f"| Q7 | 当前管理方式 | {_METHOD_LABEL[ans.current_method]} |\n"
        f"| Q8 | 决策拍板人 | {_AUTHORITY_LABEL[ans.decision_authority]} |\n"
        f"\n"
        f"## 三、PoC 建议启用动作\n"
        f"\n"
        f"{actions_block}\n"
        f"\n"
        f"> 实施工程师据此预填 `data/config/customer_<id>.actions.json`（PRD §5.2）。\n"
        f"\n"
        f"## 四、下一步\n"
        f"\n"
        f"- 销售：24h 内把本评估同步实施工程师 + 留存 CRM\n"
        f"- 实施：据 Q1 / Q8 输出客户专属 actions.json + 决策人 userid 映射\n"
        f"- 商务：以本表的"
        f"推荐年费 / ROI"
        f" 为锚做后续议价\n"
    )
