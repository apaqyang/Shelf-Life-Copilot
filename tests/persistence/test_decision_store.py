"""DecisionStore: SQLite-backed persistence for Decision log entries.

Tests use in-memory SQLite (`:memory:`) so they hit the real driver / schema /
serialization, not mocks. v0.5 will migrate to PostgreSQL by swapping this
store; the API contract verified here is what the migration must preserve.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.models import ActionType, Decision, DecisionOutcome, WorkOrder
from src.persistence import DecisionRepository, DecisionStore, WorkOrderStore


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
    def test_period_filter_compares_instants_across_timezone_offsets(
        self, store: DecisionStore
    ) -> None:
        shanghai = timezone(timedelta(hours=8))
        before_may_utc = _make_decision(
            batch_id="A-before",
            decided_at=datetime(2026, 5, 1, 7, 30, tzinfo=shanghai),
        )
        inside_may_utc = _make_decision(
            batch_id="A-inside",
            decided_at=datetime(2026, 5, 1, 8, 30, tzinfo=shanghai),
        )
        store.save(before_may_utc)
        store.save(inside_may_utc)

        results = store.list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, tzinfo=UTC),
        )

        assert [r.batch_id for r in results] == ["A-inside"]

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


def _make_work_order(decision: Decision, work_order_id: str = "WO-1") -> WorkOrder:
    return WorkOrder(
        work_order_id=work_order_id,
        batch_id=decision.batch_id,
        customer_id=decision.customer_id,
        material_name=decision.material_name,
        action=decision.action,
        created_at=decision.decided_at,
        updated_at=decision.decided_at,
    )


class TestApprovalTransaction:
    def test_approval_creates_decision_and_work_order_atomically(self, tmp_path: Path) -> None:
        path = tmp_path / "approval.db"
        decision = _make_decision()
        with DecisionStore(path) as store:
            decision_id, order, created = store.record_approval(
                decision,
                _make_work_order(decision),
                idempotency_key="event-1",
            )
            assert decision_id > 0
            assert created is True
            assert order.batch_id == decision.batch_id
        with WorkOrderStore(path) as orders:
            assert orders.get_for_batch("customerA", "A-001") == order

    def test_repeated_approval_is_idempotent(self, tmp_path: Path) -> None:
        path = tmp_path / "approval.db"
        decision = _make_decision()
        with DecisionStore(path) as store:
            first = store.record_approval(
                decision, _make_work_order(decision), idempotency_key="event-1"
            )
            second = store.record_approval(
                decision,
                _make_work_order(decision, "WO-2"),
                idempotency_key="event-2",
            )
            rows = store.list_for_period(
                "customerA",
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2027, 1, 1, tzinfo=UTC),
            )
        assert first[0] == second[0]
        assert second[1].work_order_id == "WO-1"
        assert second[2] is False
        assert len(rows) == 1

    def test_work_order_failure_rolls_back_decision(self, tmp_path: Path) -> None:
        path = tmp_path / "approval.db"
        first = _make_decision()
        second = _make_decision(batch_id="A-002")
        with DecisionStore(path) as store:
            store.record_approval(
                first, _make_work_order(first, "WO-shared"), idempotency_key="event-1"
            )
            with pytest.raises(sqlite3.IntegrityError):
                store.record_approval(
                    second,
                    _make_work_order(second, "WO-shared"),
                    idempotency_key="event-2",
                )
            rows = store.list_for_period(
                "customerA",
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2027, 1, 1, tzinfo=UTC),
            )
        assert [row.batch_id for row in rows] == ["A-001"]

    def test_rejects_invalid_approval_inputs(self, store: DecisionStore) -> None:
        approved = _make_decision()
        with pytest.raises(ValueError, match="approved"):
            snoozed = _make_decision(outcome=DecisionOutcome.SNOOZED)
            store.record_approval(snoozed, _make_work_order(snoozed), idempotency_key="event")
        with pytest.raises(ValueError, match="empty"):
            store.record_approval(approved, _make_work_order(approved), idempotency_key="")
        mismatches = (
            _make_work_order(approved).model_copy(update={"customer_id": "customerB"}),
            _make_work_order(approved).model_copy(update={"batch_id": "A-002"}),
            _make_work_order(approved).model_copy(update={"action": ActionType.DISCOUNT_CLEARANCE}),
        )
        for mismatch in mismatches:
            with pytest.raises(ValueError, match="same approval"):
                store.record_approval(approved, mismatch, idempotency_key="event")


class TestConnectionPolicy:
    def test_store_satisfies_protocol_and_context_closes(self) -> None:
        store = DecisionStore(":memory:", busy_timeout_ms=321)
        assert isinstance(store, DecisionRepository)
        assert store.busy_timeout_ms == 321
        assert store.closed is False
        with store as entered:
            assert entered is store
        assert store.closed is True

    def test_concurrent_writers_are_serialized_with_busy_timeout(self, tmp_path: Path) -> None:
        path = tmp_path / "concurrent.db"

        def write(index: int) -> int:
            with DecisionStore(path) as store:
                return store.save(_make_decision(batch_id=f"A-{index:03d}"))

        with ThreadPoolExecutor(max_workers=8) as pool:
            row_ids = list(pool.map(write, range(32)))
        assert len(set(row_ids)) == 32
        with DecisionStore(path) as store:
            rows = store.list_for_period(
                "customerA",
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2027, 1, 1, tzinfo=UTC),
            )
        assert len(rows) == 32
