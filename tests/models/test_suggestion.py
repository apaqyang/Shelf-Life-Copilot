"""Tests for the Suggestion model — validation rules and immutability."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from src.models import ActionType, Suggestion


def _base_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "batch_id": "A-001",
        "customer_id": "customerA",
        "action": ActionType.TRANSFORM,
        "savings_estimate": 8500.0,
        "rationale": "历史采纳率高，可消化全部库存。",
        "confidence": 0.85,
        "is_standard": True,
        "llm_model": "claude-sonnet-4-6",
    }
    payload.update(overrides)
    return payload


class TestSuggestionCreation:
    def test_minimal_creation_succeeds(self) -> None:
        suggestion = Suggestion(**_base_payload())
        assert suggestion.action is ActionType.TRANSFORM
        assert suggestion.is_standard is True
        assert suggestion.user_feedback is None

    def test_user_feedback_optional(self) -> None:
        suggestion = Suggestion(**_base_payload(user_feedback="虾饺线满了"))
        assert suggestion.user_feedback == "虾饺线满了"


class TestSuggestionValidation:
    def test_negative_savings_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Suggestion(**_base_payload(savings_estimate=-100.0))

    def test_confidence_above_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Suggestion(**_base_payload(confidence=1.5))

    def test_confidence_below_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Suggestion(**_base_payload(confidence=-0.1))

    def test_empty_rationale_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Suggestion(**_base_payload(rationale=""))

    def test_empty_llm_model_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Suggestion(**_base_payload(llm_model=""))


class TestSuggestionImmutability:
    def test_model_is_frozen(self) -> None:
        suggestion = Suggestion(**_base_payload())
        with pytest.raises(ValidationError):
            suggestion.action = ActionType.REPORT_LOSS  # type: ignore[misc]
