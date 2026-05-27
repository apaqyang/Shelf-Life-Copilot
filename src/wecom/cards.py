"""Pure-function renderers for the 4 v0.1 WeCom card templates.

These functions take frozen Pydantic models in, return a frozen `Card` out.
No I/O, no system clock — same inputs always produce the same markdown so
Demo runs are bit-for-bit reproducible.
"""

from __future__ import annotations

from datetime import date

from src.models import (
    ActionType,
    Alert,
    Batch,
    Card,
    CardButton,
    CardKind,
    CustomerConfig,
    Severity,
    Suggestion,
)

# Chinese fallback labels — used when CustomerConfig.industry_phrases lacks an entry.
_ACTION_FALLBACK_LABEL: dict[ActionType, str] = {
    ActionType.TRANSFORM: "转加工为下游产品",
    ActionType.DISCOUNT_CLEARANCE: "打折清仓",
    ActionType.EMPLOYEE_CANTEEN: "转员工食堂 / 关联企业消化",
    ActionType.TRANSFER_WAREHOUSE: "调拨至需求更急的分厂",
    ActionType.REPORT_LOSS: "报损处理",
}

_SEVERITY_LABEL: dict[Severity, str] = {
    Severity.NONE: "NONE",
    Severity.YELLOW: "YELLOW",
    Severity.ORANGE: "ORANGE",
    Severity.RED: "RED",
}

_DECISION_BUTTONS: tuple[CardButton, ...] = (
    CardButton(label="✅ 同意", action_key="approve"),
    CardButton(label="❌ 稍后", action_key="snooze"),
    CardButton(label="💬 改方案", action_key="revise"),
)


def _action_phrase(action: ActionType, customer: CustomerConfig) -> str:
    return customer.industry_phrases.get(action) or _ACTION_FALLBACK_LABEL[action]


def _alert_body(
    batch: Batch, alert: Alert, suggestion: Suggestion, customer: CustomerConfig
) -> str:
    phrase = _action_phrase(suggestion.action, customer)
    severity = _SEVERITY_LABEL[alert.severity]
    return (
        f"## ⚠️ 【临期预警】{batch.material_name}\n"
        f"**批号**：{batch.batch_id} ｜ **保质期**：{batch.expiry_date.isoformat()}\n"
        f"**库存**：{batch.stock_qty:,.0f} {batch.unit} ｜ "
        f"**剩余 {alert.days_left} 天** ({severity})\n"
        f"\n"
        f"> 💡 **建议**：**{phrase}**\n"
        f"> 预估节省：**¥{suggestion.savings_estimate:,.0f}** "
        f"（置信度 {suggestion.confidence:.0%}）\n"
        f">\n"
        f"> {suggestion.rationale}\n"
        f"\n"
        f"`[✅ 同意]`  `[❌ 稍后]`  `[💬 改方案]`"
    )


def render_alert_card(
    batch: Batch, alert: Alert, suggestion: Suggestion, customer: CustomerConfig
) -> Card:
    """Render the standard near-expiry alert card (PRD §5.3 sample)."""
    return Card(
        kind=CardKind.ALERT,
        customer_id=customer.customer_id,
        batch_id=batch.batch_id,
        title=f"【临期预警】{batch.material_name} · {batch.batch_id}",
        markdown=_alert_body(batch, alert, suggestion, customer),
        buttons=list(_DECISION_BUTTONS),
        mentioned_userids=list(customer.decision_makers),
        is_standard=True,
    )


def render_out_of_scope_card(
    batch: Batch, alert: Alert, suggestion: Suggestion, customer: CustomerConfig
) -> Card:
    """Same layout as alert card, but with a red "需人工复核" banner on top.

    Used when the LLM's "改方案" output picked an action outside enabled_actions
    (PRD §5.3 越界处理).
    """
    banner = "> 🚨 **⚠️ 非标准动作 · 需人工复核**\n\n"
    feedback_section = ""
    if suggestion.user_feedback:
        feedback_section = f"\n\n**用户反馈**：{suggestion.user_feedback}"
    body = banner + _alert_body(batch, alert, suggestion, customer) + feedback_section
    return Card(
        kind=CardKind.OUT_OF_SCOPE,
        customer_id=customer.customer_id,
        batch_id=batch.batch_id,
        title=f"【临期预警 · 越界】{batch.material_name} · {batch.batch_id}",
        markdown=body,
        buttons=list(_DECISION_BUTTONS),
        mentioned_userids=list(customer.decision_makers),
        is_standard=False,
    )


def render_card_for_alert(
    batch: Batch, alert: Alert, suggestion: Suggestion, customer: CustomerConfig
) -> Card:
    """Dispatch entry: route to alert vs out-of-scope card based on is_standard."""
    if suggestion.is_standard:
        return render_alert_card(batch, alert, suggestion, customer)
    return render_out_of_scope_card(batch, alert, suggestion, customer)


def render_work_order_card(
    batch: Batch,
    suggestion: Suggestion,
    customer: CustomerConfig,
    foreman_userids: list[str],
    due_date: date,
) -> Card:
    """Issued after ✅ 同意 — @s the workshop lead and asks for completion ack."""
    phrase = _action_phrase(suggestion.action, customer)
    body = (
        f"## 📋 【工单】{batch.batch_id}\n"
        f"**物料**：{batch.material_name}\n"
        f"**处置动作**：{phrase}\n"
        f"**数量**：{batch.stock_qty:,.0f} {batch.unit}\n"
        f"**截止日期**：{due_date.isoformat()}\n"
        f"\n"
        f"`[✅ 已完成]`"
    )
    return Card(
        kind=CardKind.WORK_ORDER,
        customer_id=batch.customer_id,
        batch_id=batch.batch_id,
        title=f"【工单】{batch.material_name} · {batch.batch_id}",
        markdown=body,
        buttons=[CardButton(label="✅ 已完成", action_key="complete")],
        mentioned_userids=list(foreman_userids),
    )


def render_receipt_card(batch: Batch, suggestion: Suggestion, actual_qty: float) -> Card:
    """Acknowledgement card shown after the workshop confirms completion."""
    body = (
        f"## ✅ 【工单已完成】{batch.batch_id}\n"
        f"**物料**：{batch.material_name}\n"
        f"**实际处置量**：{actual_qty:,.0f} {batch.unit}\n"
        f"**预估节省**：**¥{suggestion.savings_estimate:,.0f}**\n"
        f"\n"
        f"_决策回执已归档，本月累计节省将计入复盘报告。_"
    )
    return Card(
        kind=CardKind.RECEIPT,
        customer_id=batch.customer_id,
        batch_id=batch.batch_id,
        title=f"【工单回执】{batch.material_name} · {batch.batch_id}",
        markdown=body,
        buttons=[],
        mentioned_userids=[],
    )
