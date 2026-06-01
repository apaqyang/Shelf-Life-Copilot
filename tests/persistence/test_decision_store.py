"""DecisionStore: SQLite-backed persistence for Decision log entries.

Tests use in-memory SQLite (`:memory:`) so they hit the real driver / schema /
serialization, not mocks. v0.5 will migrate to PostgreSQL by swapping this
store; the API contract verified here is what the migration must preserve.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.models import ActionType, Decision, DecisionOutcome
from src.persistence import DecisionStore


def _make_decision(
    *,
    batch_id: str = "A-001",
    customer_id: str = "customerA",
    material_name: str = "冷冻虾仁",
    decided_at: datetime | None = None,
    action: ActionType = ActionType.TRANSFORM,
    outcome: DecisionOutcome = DecisionOutcome.APPROVED,
    savings_estimate: float = 8500.0,
    actual_savings: float | None = None,
    actual_qty: float | None = None,
    notes: str | None = None,
) -> Decision:
    return Decision(
        batch_id=batch_id,
        customer_id=customer_id,
        material_name=material_name,
        decided_at=decided_at or datetime(2026, 5, 26, 9, 0, 0, tzinfo=UTC),
        action=action,
        outcome=outcome,
        savings_estimate=savings_estimate,
        actual_savings=actual_savings,
        actual_qty=actual_qty,
        notes=notes,
    )


@pytest.fixture
def store() -> DecisionStore:
    return DecisionStore(":memory:")


class TestSaveAndList:
    def test_save_then_list_roundtrips_minimal_decision(self, store: DecisionStore) -> None:
        d = _make_decision()
        rowid = store.save(d)
        assert rowid > 0

        results = store.list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, tzinfo=UTC),
        )
        assert results == [d]

    def test_save_persists_nullable_fields(self, store: DecisionStore) -> None:
        d = _make_decision(
            actual_savings=8200.0,
            actual_qty=830.0,
            notes="车间反馈：略低于估算",
        )
        store.save(d)
        results = store.list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, tzinfo=UTC),
        )
        assert len(results) == 1
        got = results[0]
        assert got.actual_savings == 8200.0
        assert got.actual_qty == 830.0
        assert got.notes == "车间反馈：略低于估算"

    def test_non_utc_tz_preserved_through_roundtrip(self, store: DecisionStore) -> None:
        """Asia/Shanghai (+08:00) decisions must come back tz-aware and identical."""
        shanghai = timezone(timedelta(hours=8))
        d = _make_decision(decided_at=datetime(2026, 5, 26, 17, 30, tzinfo=shanghai))
        store.save(d)
        results = store.list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, tzinfo=UTC),
        )
        assert results[0].decided_at == d.decided_at
        assert results[0].decided_at.tzinfo is not None


class TestPeriodFiltering:
    def test_excludes_decisions_outside_window(self, store: DecisionStore) -> None:
        early = _make_decision(
            batch_id="A-001", decided_at=datetime(2026, 4, 30, 23, 59, tzinfo=UTC)
        )
        in_window = _make_decision(
            batch_id="A-002", decided_at=datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
        )
        late = _make_decision(
            batch_id="A-003", decided_at=datetime(2026, 6, 1, 0, 0, 1, tzinfo=UTC)
        )
        for d in (early, in_window, late):
            store.save(d)

        results = store.list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, tzinfo=UTC),
        )
        assert [r.batch_id for r in results] == ["A-002"]

    def test_start_inclusive_end_exclusive(self, store: DecisionStore) -> None:
        on_start = _make_decision(
            batch_id="A-S", decided_at=datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)
        )
        on_end = _make_decision(
            batch_id="A-E", decided_at=datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        )
        for d in (on_start, on_end):
            store.save(d)

        results = store.list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, tzinfo=UTC),
        )
        assert [r.batch_id for r in results] == ["A-S"]

    def test_filters_by_customer_id(self, store: DecisionStore) -> None:
        a = _make_decision(batch_id="A-001", customer_id="customerA")
        b = _make_decision(batch_id="B-001", customer_id="customerB")
        store.save(a)
        store.save(b)

        results = store.list_for_period(
            "customerB",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, tzinfo=UTC),
        )
        assert [r.batch_id for r in results] == ["B-001"]

    def test_results_sorted_ascending_by_decided_at(self, store: DecisionStore) -> None:
        d_late = _make_decision(batch_id="A-late", decided_at=datetime(2026, 5, 20, tzinfo=UTC))
        d_early = _make_decision(batch_id="A-early", decided_at=datetime(2026, 5, 5, tzinfo=UTC))
        d_mid = _make_decision(batch_id="A-mid", decided_at=datetime(2026, 5, 12, tzinfo=UTC))
        # Insert out of order to prove sorting comes from query, not insert order
        for d in (d_late, d_early, d_mid):
            store.save(d)

        results = store.list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, tzinfo=UTC),
        )
        assert [r.batch_id for r in results] == ["A-early", "A-mid", "A-late"]


class TestPersistenceAcrossInstances:
    """File-backed store must survive process restart (sanity for v0.5 deployment)."""

    def test_file_db_persists_across_instances(self, tmp_path: Path) -> None:
        db_file = tmp_path / "decisions.db"
        DecisionStore(db_file).save(_make_decision())

        # Reopen — same data must be there
        results = DecisionStore(db_file).list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, tzinfo=UTC),
        )
        assert len(results) == 1
        assert results[0].batch_id == "A-001"

    def test_schema_init_is_idempotent(self, tmp_path: Path) -> None:
        """Calling DecisionStore(path) twice on the same file must not error."""
        db_file = tmp_path / "decisions.db"
        DecisionStore(db_file)
        DecisionStore(db_file)  # should not raise — CREATE TABLE IF NOT EXISTS

    def test_empty_period_returns_empty_list(self, store: DecisionStore) -> None:
        results = store.list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, tzinfo=UTC),
        )
        assert results == []


class TestNaiveDatetimeRejected:
    """The Decision model rejects naive datetimes; store must not silently accept them either."""

    def test_naive_start_or_end_raises(self, store: DecisionStore) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            store.list_for_period(
                "customerA",
                start=datetime(2026, 5, 1),  # naive
                end=datetime(2026, 6, 1, tzinfo=UTC),
            )
        with pytest.raises(ValueError, match="timezone-aware"):
            store.list_for_period(
                "customerA",
                start=datetime(2026, 5, 1, tzinfo=UTC),
                end=datetime(2026, 6, 1),  # naive
            )
