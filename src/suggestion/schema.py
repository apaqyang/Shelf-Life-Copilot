"""Tool definition forcing strict JSON output via tool_use / function calling.

Schema design (PRD §5.3 越界兜底):
- `action` enum spans the *full* ActionType set, not just `enabled_actions`.
- The SYSTEM_PROMPT instructs the model to prefer enabled actions, and only
  reach for a disabled one when the user's 改方案 feedback explicitly asks for
  it. `is_standard` is then derived deterministically by Python:
  `action in customer.enabled_actions`.

This lets the LLM physically emit out-of-scope actions when the user requests
them, so the "⚠️ 非标准动作 · 需人工复核" red-banner flow can actually fire.
"""

from __future__ import annotations

from typing import Any

from src.models.action import ActionType

TOOL_NAME = "submit_suggestion"


def build_suggestion_tool(enabled_actions: list[ActionType]) -> dict[str, Any]:
    """Build the suggestion-tool spec. `enabled_actions` informs the description;
    the enum itself spans the full ActionType set (see module docstring).

    Raises:
        ValueError: when `enabled_actions` is empty.
    """
    if not enabled_actions:
        raise ValueError("enabled_actions must contain at least one ActionType")

    enabled_values = [a.value for a in enabled_actions]
    all_values = [a.value for a in ActionType]
    enabled_str = ", ".join(enabled_values)

    return {
        "name": TOOL_NAME,
        "description": (
            "Submit one disposal suggestion for the near-expiry batch. "
            "Choose exactly one action and provide savings, rationale, and confidence."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": all_values,
                    "description": (
                        "The chosen disposal action. STRONGLY PREFER one of the "
                        f"customer-enabled actions: [{enabled_str}]. Only pick a "
                        "non-enabled action when the user's 改方案 feedback "
                        "explicitly asks for it — that case is treated as a "
                        "non-standard recommendation and routed to human review."
                    ),
                },
                "savings_estimate": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Estimated CNY savings if this action is executed.",
                },
                "rationale": {
                    "type": "string",
                    "description": "中文理由，≤ 50 字。",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "Confidence in this recommendation (0 = guess, 1 = certain).",
                },
            },
            "required": ["action", "savings_estimate", "rationale", "confidence"],
        },
    }
