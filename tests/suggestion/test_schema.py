"""Tests for the Anthropic tool schema builder."""

from __future__ import annotations

from typing import Any, cast

import pytest

from src.models import ActionType
from src.suggestion.schema import TOOL_NAME, build_suggestion_tool


class TestBuildSuggestionTool:
    def test_tool_name_is_constant(self) -> None:
        tool = build_suggestion_tool([ActionType.TRANSFORM])
        assert tool["name"] == TOOL_NAME

    def test_action_enum_restricted_to_enabled_actions(self) -> None:
        tool = build_suggestion_tool([ActionType.TRANSFORM, ActionType.REPORT_LOSS])
        properties = cast(dict[str, Any], tool["input_schema"])["properties"]
        action_enum = properties["action"]["enum"]
        assert action_enum == ["transform", "report_loss"]

    def test_required_fields_complete(self) -> None:
        tool = build_suggestion_tool([ActionType.TRANSFORM])
        required = cast(dict[str, Any], tool["input_schema"])["required"]
        assert set(required) == {"action", "savings_estimate", "rationale", "confidence"}

    def test_confidence_bounded_to_0_1(self) -> None:
        tool = build_suggestion_tool([ActionType.TRANSFORM])
        confidence_schema = cast(dict[str, Any], tool["input_schema"])["properties"]["confidence"]
        assert confidence_schema["minimum"] == 0
        assert confidence_schema["maximum"] == 1

    def test_savings_estimate_non_negative(self) -> None:
        tool = build_suggestion_tool([ActionType.TRANSFORM])
        savings_schema = cast(dict[str, Any], tool["input_schema"])["properties"][
            "savings_estimate"
        ]
        assert savings_schema["minimum"] == 0

    def test_empty_actions_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            build_suggestion_tool([])
