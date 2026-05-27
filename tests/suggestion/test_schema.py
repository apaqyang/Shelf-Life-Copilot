"""Tests for the suggestion tool schema builder."""

from __future__ import annotations

from typing import Any, cast

import pytest

from src.models import ActionType
from src.suggestion.schema import TOOL_NAME, build_suggestion_tool


class TestBuildSuggestionTool:
    def test_tool_name_is_constant(self) -> None:
        tool = build_suggestion_tool([ActionType.TRANSFORM])
        assert tool["name"] == TOOL_NAME

    def test_action_enum_spans_all_actions(self) -> None:
        # PRD §5.3 越界兜底：enum 是全集，is_standard 由 Python 判断。
        tool = build_suggestion_tool([ActionType.TRANSFORM, ActionType.REPORT_LOSS])
        properties = cast(dict[str, Any], tool["input_schema"])["properties"]
        action_enum = properties["action"]["enum"]
        assert set(action_enum) == {a.value for a in ActionType}

    def test_description_lists_enabled_actions_as_preferred(self) -> None:
        tool = build_suggestion_tool([ActionType.TRANSFORM, ActionType.REPORT_LOSS])
        properties = cast(dict[str, Any], tool["input_schema"])["properties"]
        description = properties["action"]["description"]
        assert "transform" in description
        assert "report_loss" in description
        # The description must steer the model toward enabled actions.
        assert "PREFER" in description or "prefer" in description.lower()

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
