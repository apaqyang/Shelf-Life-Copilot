"""SuggestionStore — persist LLM suggestions for downstream lookup.

The webhook click handler queries `latest_for_batch` to fill Decision.action
and savings_estimate with the true LLM values instead of TRANSFORM/0.0
placeholders. Tests target that contract (single source of truth = "latest").
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.models import ActionType, Suggestion
from src.persistence import SuggestionStore


def _make_suggestion(
    *,
    batch_id: str = "A-001",
    customer_id: str = "customerA",
    action: ActionType = ActionType.TRANSFORM,
    savings_estimate: float = 8500.0,
    rationale: str = "rationale",
    confidence: float = 0.85,
    is_standard: bool = True,
    generated_at: datetime | None = None,
    llm_model: str = "claude-sonnet-4-6",
    user_feedback: str | None = None,
) -> Suggestion:
    return Suggestion(
        batch_id=batch_id,
        customer_id=customer_id,
        action=action,
        savings_estimate=savings_estimate,
        rationale=rationale,
        confidence=confidence,
        is_standard=is_standard,
        generated_at=generated_at or datetime(2026, 5, 26, 9, 0, tzinfo=UTC),
        llm_model=llm_model,
        user_feedback=user_feedback,
    )


@pytest.fixture
def store() -> SuggestionStore:
    return SuggestionStore(":memory:")


class TestSaveAndLookup:
    def test_save_then_latest_roundtrips(self, store: SuggestionStore) -> None:
        s = _make_suggestion()
        rowid = store.save(s)
        assert rowid > 0

        got = store.latest_for_batch("customerA", "A-001")
        assert got == s

    def test_nullable_user_feedback_preserved(self, store: SuggestionStore) -> None:
        with_fb = _make_suggestion(user_feedback="虾饺线满了，改打折")
        store.save(with_fb)
        got = store.latest_for_batch("customerA", "A-001")
        assert got is not None
        assert got.user_feedback == "虾饺线满了，改打折"

    def test_non_standard_flag_preserved(self, store: SuggestionStore) -> None:
        s = _make_suggestion(
            action=ActionType.EMPLOYEE_CANTEEN,
            is_standard=False,
        )
        store.save(s)
        got = store.latest_for_batch("customerA", "A-001")
        assert got is not None
        assert got.is_standard is False
        assert got.action is ActionType.EMPLOYEE_CANTEEN

    def test_missing_returns_none(self, store: SuggestionStore) -> None:
        assert store.latest_for_batch("customerA", "A-001") is None

    def test_filters_by_customer_id(self, store: SuggestionStore) -> None:
        a = _make_suggestion(customer_id="customerA", batch_id="A-001")
        b = _make_suggestion(customer_id="customerB", batch_id="A-001")
        store.save(a)
        store.save(b)

        got_a = store.latest_for_batch("customerA", "A-001")
        got_b = store.latest_for_batch("customerB", "A-001")
        assert got_a is not None and got_a.customer_id == "customerA"
        assert got_b is not None and got_b.customer_id == "customerB"


class TestLatestOrdering:
    def test_latest_wins_on_generated_at(self, store: SuggestionStore) -> None:
        early = _make_suggestion(
            generated_at=datetime(2026, 5, 26, 7, 0, tzinfo=UTC),
            savings_estimate=8500.0,
        )
        mid = _make_suggestion(
            generated_at=datetime(2026, 5, 26, 9, 0, tzinfo=UTC),
            savings_estimate=6200.0,
            action=ActionType.DISCOUNT_CLEARANCE,
        )
        late = _make_suggestion(
            generated_at=datetime(2026, 5, 26, 11, 0, tzinfo=UTC),
            savings_estimate=1500.0,
            action=ActionType.EMPLOYEE_CANTEEN,
            is_standard=False,
            user_feedback="送给关联食堂",
        )
        # Save out of chronological order to prove latest comes from the data, not insert order.
        store.save(mid)
        store.save(early)
        store.save(late)

        got = store.latest_for_batch("customerA", "A-001")
        assert got is not None
        assert got.savings_estimate == 1500.0
        assert got.action is ActionType.EMPLOYEE_CANTEEN
        assert got.user_feedback == "送给关联食堂"


class TestFilePersistence:
    """File-backed store survives process restart — sanity for v0.5 deployment."""

    def test_file_db_persists_across_instances(self, tmp_path: Path) -> None:
        db_file = tmp_path / "suggestions.db"
        SuggestionStore(db_file).save(_make_suggestion())

        got = SuggestionStore(db_file).latest_for_batch("customerA", "A-001")
        assert got is not None
        assert got.batch_id == "A-001"

    def test_schema_init_is_idempotent(self, tmp_path: Path) -> None:
        db_file = tmp_path / "suggestions.db"
        SuggestionStore(db_file)
        SuggestionStore(db_file)  # CREATE TABLE IF NOT EXISTS

    def test_shares_db_with_decision_store(self, tmp_path: Path) -> None:
        """Two stores on the same file must not clash — they own different tables."""
        from datetime import UTC, datetime

        from src.models import Decision, DecisionOutcome
        from src.persistence import DecisionStore

        db = tmp_path / "shared.db"
        SuggestionStore(db).save(_make_suggestion())
        DecisionStore(db).save(
            Decision(
                batch_id="A-001",
                customer_id="customerA",
                material_name="冷冻虾仁",
                decided_at=datetime(2026, 5, 26, 10, tzinfo=UTC),
                action=ActionType.TRANSFORM,
                outcome=DecisionOutcome.APPROVED,
                savings_estimate=8500.0,
            )
        )

        got_s = SuggestionStore(db).latest_for_batch("customerA", "A-001")
        got_d = DecisionStore(db).list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, tzinfo=UTC),
        )
        assert got_s is not None
        assert len(got_d) == 1


class TestTimezoneFidelity:
    def test_non_utc_tz_preserved(self, store: SuggestionStore) -> None:
        from datetime import timezone

        shanghai = timezone(timedelta(hours=8))
        s = _make_suggestion(generated_at=datetime(2026, 5, 26, 17, 30, tzinfo=shanghai))
        store.save(s)
        got = store.latest_for_batch("customerA", "A-001")
        assert got is not None
        assert got.generated_at == s.generated_at
        assert got.generated_at.tzinfo is not None
