from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from typing import Any

import pytest

from src.models import (
    ActionType,
    Decision,
    DecisionOutcome,
    Suggestion,
    WorkOrder,
    WorkOrderReceipt,
    WorkOrderStatus,
)
from src.persistence.postgres import (
    PostgresDecisionStore,
    PostgresSuggestionStore,
    PostgresWorkOrderStore,
    run_postgres_migrations,
)


class FakeCursor:
    def __init__(self) -> None:
        self.fetchone_values: deque[tuple[object, ...] | None] = deque()
        self.fetchall_value: list[tuple[object, ...]] = []
        self.queries: list[tuple[str, tuple[object, ...]]] = []
        self.fail_once: Exception | None = None
        self.fail_contains: str | None = None

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeCursor:
        self.queries.append((query, params))
        if self.fail_once is not None:
            error, self.fail_once = self.fail_once, None
            raise error
        if self.fail_contains is not None and self.fail_contains in query:
            self.fail_contains = None
            raise RuntimeError("write failed")
        return self

    def fetchone(self) -> tuple[object, ...] | None:
        return self.fetchone_values.popleft()

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.fetchall_value


class FakeConnection:
    def __init__(self) -> None:
        self.the_cursor = FakeCursor()
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.the_cursor

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def _decision() -> Decision:
    return Decision(
        batch_id="b",
        customer_id="c",
        material_name="food",
        decided_at=datetime(2026, 1, 1, tzinfo=UTC),
        action=ActionType.REPORT_LOSS,
        outcome=DecisionOutcome.APPROVED,
        savings_estimate=10,
    )


def _suggestion() -> Suggestion:
    return Suggestion(
        batch_id="b",
        customer_id="c",
        action=ActionType.REPORT_LOSS,
        savings_estimate=10,
        rationale="why",
        confidence=0.8,
        is_standard=True,
        llm_model="local",
    )


def _store(cls: type[Any], connection: FakeConnection) -> Any:
    store = object.__new__(cls)
    store._connection = connection
    return store


def test_postgres_migration_commits_and_rolls_back() -> None:
    connection = FakeConnection()
    run_postgres_migrations(connection)
    assert connection.commits == 1
    assert len(connection.the_cursor.queries) >= 5
    broken = FakeConnection()
    broken.the_cursor.fail_once = RuntimeError("ddl failed")
    with pytest.raises(RuntimeError, match="ddl failed"):
        run_postgres_migrations(broken)
    assert broken.rollbacks == 1
    decision_connection = FakeConnection()
    PostgresDecisionStore(decision_connection).close()
    suggestion_connection = FakeConnection()
    PostgresSuggestionStore(suggestion_connection).close()
    work_order_connection = FakeConnection()
    PostgresWorkOrderStore(work_order_connection).close()


def test_postgres_decision_contract_and_approval_paths() -> None:
    connection = FakeConnection()
    store: PostgresDecisionStore = _store(PostgresDecisionStore, connection)
    connection.the_cursor.fetchone_values.append((7,))
    assert store.save(_decision()) == 7
    row = (
        "b",
        "c",
        "food",
        datetime(2026, 1, 1, tzinfo=UTC),
        "report_loss",
        "approved",
        10.0,
        None,
        None,
        None,
    )
    connection.the_cursor.fetchall_value = [row]
    assert store.list_for_period(
        "c", datetime(2025, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)
    ) == [_decision()]
    with pytest.raises(ValueError, match="timezone-aware"):
        store.list_for_period("c", datetime(2025, 1, 1), datetime(2027, 1, 1, tzinfo=UTC))
    order = WorkOrder(
        work_order_id="wo",
        batch_id="b",
        customer_id="c",
        material_name="food",
        action=ActionType.REPORT_LOSS,
    )
    with pytest.raises(ValueError, match="approved"):
        store.record_approval(
            _decision().model_copy(update={"outcome": DecisionOutcome.SNOOZED}),
            order,
            idempotency_key="snoozed",
        )
    with pytest.raises(ValueError, match="idempotency_key"):
        store.record_approval(_decision(), order, idempotency_key="")
    with pytest.raises(ValueError, match="same approval"):
        store.record_approval(
            _decision(),
            order.model_copy(update={"batch_id": "different"}),
            idempotency_key="different",
        )
    connection.the_cursor.fetchone_values.append((8,))
    assert store.record_approval(_decision(), order, idempotency_key="new") == (8, order, True)

    connection.the_cursor.fail_once = RuntimeError("unique")
    connection.the_cursor.fetchone_values.append(
        (8, "wo", "b", "c", "food", "report_loss", "pending", order.created_at, order.updated_at)
    )
    assert store.record_approval(_decision(), order, idempotency_key="same") == (8, order, False)

    connection.the_cursor.fail_once = RuntimeError("database down")
    connection.the_cursor.fetchone_values.append(None)
    with pytest.raises(RuntimeError, match="database down"):
        store.record_approval(_decision(), order, idempotency_key="missing")
    store.close()
    assert connection.closed


def test_postgres_suggestion_contract() -> None:
    connection = FakeConnection()
    store: PostgresSuggestionStore = _store(PostgresSuggestionStore, connection)
    suggestion = _suggestion()
    connection.the_cursor.fetchone_values.append((4,))
    assert store.save(suggestion) == 4
    connection.the_cursor.fetchone_values.append(None)
    assert store.latest_for_batch("c", "missing") is None
    connection.the_cursor.fetchone_values.append(
        (
            "b",
            "c",
            "report_loss",
            10.0,
            "why",
            0.8,
            True,
            "local",
            None,
            suggestion.generated_at,
        )
    )
    assert store.latest_for_batch("c", "b") == suggestion
    store.close()
    assert connection.closed


def _order_row(order: WorkOrder) -> tuple[object, ...]:
    return (
        order.work_order_id,
        order.batch_id,
        order.customer_id,
        order.material_name,
        order.action.value,
        order.status.value,
        order.created_at,
        order.updated_at,
        order.actual_qty,
        order.actual_savings,
        order.completed_by,
        order.completed_at,
        order.completion_source,
    )


def test_postgres_work_order_contract_and_transaction_paths() -> None:
    connection = FakeConnection()
    store: PostgresWorkOrderStore = _store(PostgresWorkOrderStore, connection)
    pending = WorkOrder(
        work_order_id="wo",
        batch_id="b",
        customer_id="c",
        material_name="food",
        action=ActionType.REPORT_LOSS,
    )
    connection.the_cursor.fetchone_values.extend([_order_row(pending), None])
    assert store.get_for_batch("c", "b") == pending
    assert store.get("missing") is None

    connection.the_cursor.fetchone_values.append(_order_row(pending))
    started = store.transition("wo", WorkOrderStatus.IN_PROGRESS, at=pending.updated_at)
    assert started.status is WorkOrderStatus.IN_PROGRESS
    connection.the_cursor.fetchone_values.append(None)
    with pytest.raises(KeyError):
        store.transition("missing", WorkOrderStatus.IN_PROGRESS, at=pending.updated_at)

    receipt = WorkOrderReceipt(
        actual_qty=1,
        actual_savings=2,
        completed_by="worker",
        completed_at=pending.updated_at,
        source="api",
    )
    connection.the_cursor.fetchone_values.append(_order_row(started))
    assert store.complete("wo", receipt).status is WorkOrderStatus.COMPLETED
    connection.the_cursor.fetchone_values.append(None)
    with pytest.raises(KeyError):
        store.complete("missing", receipt)

    connection.the_cursor.fetchone_values.append(_order_row(started))
    connection.the_cursor.fail_contains = "UPDATE work_orders"
    with pytest.raises(RuntimeError, match="write failed"):
        store.complete("wo", receipt)
    assert connection.rollbacks >= 1
    store.close()
