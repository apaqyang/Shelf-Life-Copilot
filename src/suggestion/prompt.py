"""Prompt construction for the suggestion LLM call."""

from __future__ import annotations

from src.models import ActionType, Batch, CustomerConfig
from src.models.alert import Alert

SYSTEM_PROMPT = (
    "你是一家食品厂的临期处置专家。对每个临期批次，你必须从客户启用的动作集合中"
    "选择一个最合适的动作，并通过 submit_suggestion 工具提交建议。\n\n"
    "硬约束：\n"
    "- 只能从可选动作中选择（工具的 enum 已限定）\n"
    "- 必须给出预估节省金额（人民币，参考批次均值）\n"
    "- rationale 必须 ≤ 50 字中文\n"
    "- confidence 在 0-1 之间，越高表示越确定"
)


def format_actions_block(
    enabled_actions: list[ActionType],
    industry_phrases: dict[ActionType, str],
) -> str:
    """Format enabled actions + their industry phrases as a prompt block."""
    lines = [
        f"- {action.value}: {industry_phrases.get(action, action.value)}"
        for action in enabled_actions
    ]
    return "\n".join(lines)


def build_user_prompt(
    batch: Batch,
    alert: Alert,
    customer: CustomerConfig,
    feedback: str | None = None,
) -> str:
    """Build the user-facing prompt with batch context + customer constraints."""
    actions_block = format_actions_block(customer.enabled_actions, customer.industry_phrases)

    sections = [
        f"批次：{batch.material_name}（批号 {batch.batch_id}）",
        f"库存：{batch.stock_qty:g} {batch.unit}",
        f"剩余天数：{alert.days_left} 天（紧急程度：{alert.severity.value}）",
        f"客户行业：{customer.industry}",
        f"参考节省金额（单批次均值）：¥{customer.avg_savings_per_batch:,.0f}",
        "",
        "可选动作：",
        actions_block,
    ]

    if feedback:
        sections.extend(
            [
                "",
                "用户反馈（请基于此重新生成建议）：",
                feedback,
                "",
                "若反馈中提及的动作不在可选清单中，请选择语义最接近的动作，"
                "并在 rationale 中明确说明实际意图与映射理由。",
            ]
        )

    return "\n".join(sections)
