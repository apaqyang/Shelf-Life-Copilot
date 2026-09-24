from __future__ import annotations

from pathlib import Path

import pytest

from src.evaluation import SuggestionEvalCase, load_eval_cases, score_standardness
from src.models import ActionType, Suggestion


def _suggestion(standard: bool) -> Suggestion:
    return Suggestion(
        batch_id="b",
        customer_id="c",
        action=ActionType.REPORT_LOSS,
        savings_estimate=1,
        rationale="test",
        confidence=1,
        is_standard=standard,
        llm_model="test",
    )


def test_sanitized_dataset_has_required_categories() -> None:
    cases = load_eval_cases(Path("data/evals/suggestion_cases.json"))
    assert len(cases) == 4
    assert score_standardness(cases, [_suggestion(c.expected_standard) for c in cases]) == 1


def test_dataset_and_score_validation(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text(
        '[{"case_id":"x","category":"standard","days_left":1,"stock_qty":1,"enabled_actions":["report_loss"],"expected_standard":true}]'
    )
    with pytest.raises(ValueError, match="missing required"):
        load_eval_cases(path)
    case = SuggestionEvalCase(
        case_id="x",
        category="standard",
        days_left=1,
        stock_qty=1,
        enabled_actions=[ActionType.REPORT_LOSS],
        expected_standard=True,
    )
    with pytest.raises(ValueError, match="aligned"):
        score_standardness([case], [])
