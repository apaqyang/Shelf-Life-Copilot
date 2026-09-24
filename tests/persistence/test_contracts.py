"""Shared persistence contracts; add future adapters to the factory parameters."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.models import ActionType, Decision, DecisionOutcome, Suggestion
from src.persistence import (
    DecisionRepository,
    DecisionStore,
    SuggestionRepository,
    SuggestionStore,
)


@pytest.fixture(params=[pytest.param(DecisionStore, id="sqlite")])
def decision_repository(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[DecisionRepository]:
    factory = request.param
    assert isinstance(factory, Callable)
    repository: DecisionRepository = factory(tmp_path / "decisions.db")
    yield repository
    repository.close()


@pytest.fixture(params=[pytest.param(SuggestionStore, id="sqlite")])
def suggestion_repository(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[SuggestionRepository]:
    factory = request.param
    assert isinstance(factory, Callable)
    repository: SuggestionRepository = factory(tmp_path / "suggestions.db")
    yield repository
    repository.close()


def test_decision_repository_roundtrip(decision_repository: DecisionRepository) -> None:
    timestamp = datetime(2026, 9, 23, tzinfo=UTC)
    decision = Decision(
        batch_id="A-001",
        customer_id="customerA",
        material_name="冷冻虾仁",
        decided_at=timestamp,
        action=ActionType.TRANSFORM,
        outcome=DecisionOutcome.APPROVED,
        savings_estimate=100,
    )
    assert decision_repository.save(decision) > 0
    assert decision_repository.list_for_period(
        "customerA",
        datetime(2026, 9, 1, tzinfo=UTC),
        datetime(2026, 10, 1, tzinfo=UTC),
    ) == [decision]


def test_suggestion_repository_latest_contract(
    suggestion_repository: SuggestionRepository,
) -> None:
    early = Suggestion(
        batch_id="A-001",
        customer_id="customerA",
        action=ActionType.TRANSFORM,
        savings_estimate=100,
        rationale="early",
        confidence=0.8,
        is_standard=True,
        llm_model="offline",
        generated_at=datetime(2026, 9, 22, tzinfo=UTC),
    )
    late = early.model_copy(
        update={
            "action": ActionType.DISCOUNT_CLEARANCE,
            "generated_at": datetime(2026, 9, 23, tzinfo=UTC),
        }
    )
    suggestion_repository.save(late)
    suggestion_repository.save(early)
    assert suggestion_repository.latest_for_batch("customerA", "A-001") == late
    assert suggestion_repository.latest_for_batch("customerB", "A-001") is None
