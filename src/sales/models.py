"""Lead-qualification models — input/output for PRD §12.1 sales survey.

The 8-question survey lives at the boundary between sales and engineering:
- Sales fills it during the first customer meeting (5 min target)
- Engineering uses Q1/Q7 to pre-fill the customer's actions JSON
- Both use Q5 to anchor the v1.0 annual fee

These models are the typed interchange format. Tools layer (`tools/qualify_lead.py`)
handles UI; this layer only knows about the data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat


class IndustryCategory(StrEnum):
    """Q1 主营品类 — drives recommended_pilot_actions presets."""

    FROZEN_RAW = "frozen_raw"  # 冷冻原料
    READY_MEAL = "ready_meal"  # 预制菜
    BAKERY = "bakery"  # 烘焙
    SNACKS = "snacks"  # 休闲食品
    FRESH_PROCESSING = "fresh_processing"  # 生鲜加工
    OTHER = "other"


class AnnualLossBand(StrEnum):
    """Q5 去年报损/临期处置金额档位 — directly drives v1.0 annual fee tier."""

    UNDER_50W = "under_50w"  # < 50 万
    BETWEEN_50_100W = "50w_100w"  # 50-100 万
    BETWEEN_100_300W = "100w_300w"  # 100-300 万
    OVER_300W = "over_300w"  # > 300 万
    UNKNOWN = "unknown"  # 答不出 — fall back to Q6 monthly estimate


class CurrentMethod(StrEnum):
    """Q7 当前临期管理方式 — pain-strength signal."""

    WORKSHOP_EXPERIENCE = "workshop_experience"  # 完全凭车间经验
    EXCEL = "excel"  # 人工 Excel
    ERP_REPORT = "erp_report"  # ERP 报表
    SPECIALIZED_TOOL = "specialized_tool"  # 已有专门工具（替换成本高）


class DecisionAuthority(StrEnum):
    """Q8 决策拍板人 — gates priority (multi-party deals get deprioritized)."""

    SUPPLY_CHAIN_DIRECTOR = "supply_chain_director"
    PURCHASING_DIRECTOR = "purchasing_director"
    PRODUCTION_DIRECTOR = "production_director"
    OWNER = "owner"
    MULTI_PARTY = "multi_party"


class PriorityTier(StrEnum):
    """Output of priority rules — ranks the lead in PoC queue.

    GOLD/SILVER/BRONZE/SKIP map 1:1 to PRD §12.1's ⭐⭐⭐/⭐⭐/⭐/❌ rows.
    """

    GOLD = "gold"
    SILVER = "silver"
    BRONZE = "bronze"
    SKIP = "skip"


# Free-text bands for Q2 / Q3 / Q4 — we keep them as raw strings since they
# don't drive any business logic, only land verbatim in the CRM record.
class LeadAnswers(BaseModel):
    """Raw answers to the 8-question survey, exactly as sales captured them."""

    model_config = ConfigDict(frozen=True)

    customer_name: str = Field(min_length=1)
    industry: IndustryCategory  # Q1
    annual_procurement_band: str = Field(min_length=1)  # Q2
    sku_count_band: str = Field(min_length=1)  # Q3
    avg_shelf_life_band: str = Field(min_length=1)  # Q4
    annual_loss_band: AnnualLossBand  # Q5
    monthly_loss_estimate_yuan: NonNegativeFloat | None = None  # Q6, when Q5=UNKNOWN
    current_method: CurrentMethod  # Q7
    decision_authority: DecisionAuthority  # Q8


class LeadAssessment(BaseModel):
    """Computed lead assessment — what sales takes away from the survey."""

    model_config = ConfigDict(frozen=True)

    customer_name: str
    industry: IndustryCategory
    annual_loss_band: AnnualLossBand
    annual_loss_estimate_yuan: NonNegativeFloat
    recommended_annual_fee_yuan: NonNegativeFloat
    estimated_annual_savings_yuan: NonNegativeFloat
    roi_multiple: NonNegativeFloat
    priority_tier: PriorityTier
    recommended_pilot_actions: list[str]  # ActionType.value, kept as str for JSON portability
    sales_pitch: str  # one-line from PRD §12.1 sales script
    raw_answers: LeadAnswers
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
