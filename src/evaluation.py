"""Sanitized suggestion-quality regression cases and baseline scoring."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from src.models import ActionType, Suggestion


class SuggestionEvalCase(BaseModel):
    case_id: str
    category: str
    days_left: int
    stock_qty: float = Field(ge=0)
    enabled_actions: list[ActionType] = Field(min_length=1)
    feedback: str | None = None
    expected_standard: bool


def load_eval_cases(path: Path) -> list[SuggestionEvalCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = [SuggestionEvalCase.model_validate(item) for item in payload]
    required = {"standard", "out_of_scope", "missing_data", "extreme_days"}
    if not required.issubset({case.category for case in cases}):
        raise ValueError("evaluation dataset is missing required categories")
    return cases


def score_standardness(cases: list[SuggestionEvalCase], suggestions: list[Suggestion]) -> float:
    if len(cases) != len(suggestions) or not cases:
        raise ValueError("cases and suggestions must be non-empty and aligned")
    correct = sum(
        case.expected_standard == suggestion.is_standard
        for case, suggestion in zip(cases, suggestions, strict=True)
    )
    return correct / len(cases)
