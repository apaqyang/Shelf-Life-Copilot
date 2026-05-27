"""Prompt construction for the suggestion LLM call."""

from __future__ import annotations

from src.models import ActionType, Batch, CustomerConfig
from src.models.alert import Alert

SYSTEM_PROMPT = (
    "你是一家食品厂的临期处置专家。对每个临期批次，通过 submit_suggestion 工具"
    "提交一个最合适的处置动作建议。\n\n"
    "选择规则（按优先级）：\n"
    "1. **优先**从客户启用的动作集合（见用户消息中的『可选动作』清单）中选择。\n"
    "2. 仅当用户反馈中明确要求执行启用集合之外的动作时（例如用户说『送给关联食堂』"
    "但 employee_canteen 不在启用集合），可以选择该非标准动作并照实输出。\n"
    "   此时 rationale 第一句必须用『用户特别要求』开头，便于后台标注为非标准动作。\n"
    "3. 没有用户反馈、或反馈未明确指定动作时，禁止跨出启用集合。\n\n"
    "硬约束：\n"
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
                "处理规则：",
                "- 若反馈在可选动作范围内，直接选对应动作。",
                "- 若反馈明确要求**可选清单之外**的动作（例如启用集合不含 employee_canteen"
                " 但用户说『送给员工食堂』），按 SYSTEM_PROMPT 规则 2，仍输出用户要求的"
                "非标准动作，rationale 以『用户特别要求』开头。",
            ]
        )

    return "\n".join(sections)
