"""Anthropic tool definition forcing strict JSON output via tool_use.

The `action` field's `enum` is dynamically restricted to the customer's
`enabled_actions` — Claude is constrained at generation time, no post-filter needed.
"""

from __future__ import annotations

from typing import Any

from src.models.action import ActionType

TOOL_NAME = "submit_suggestion"


def build_suggestion_tool(enabled_actions: list[ActionType]) -> dict[str, Any]:
    """Build the Anthropic tool spec for one suggestion.

    Raises:
        ValueError: when `enabled_actions` is empty (Claude requires at least one enum value).
    """
    if not enabled_actions:
        raise ValueError("enabled_actions must contain at least one ActionType")

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
                    "enum": [a.value for a in enabled_actions],
                    "description": "The chosen disposal action (must be one of the listed enum values).",
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
