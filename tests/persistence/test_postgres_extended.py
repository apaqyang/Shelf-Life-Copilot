from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from src.models import ActionType, WorkOrder, WorkOrderStatus
from src.optimization import (
    OptimizationBatch,
    OptimizationPlan,
    OptimizationPlanStatus,
    OptimizationRequest,
    priority_baseline,
)
from src.persistence import SecurityAuditEvent
from src.persistence.postgres import (
    PostgresDatabase,
    PostgresIdempotencyStore,
    PostgresOptimizationPlanStore,
    PostgresRateLimiter,
    PostgresRevisionStore,
    PostgresSecurityAuditStore,
    PostgresWorkOrderStore,
    _is_integrity_error,
)


class FakeIntegrityError(Exception):
    pass


class FakeCursor:
    def __init__(self) -> None:
        self.fetchone_values: deque[tuple[object, ...] | None] = deque()
        self.fetchall_value: list[tuple[object, ...]] = []
        self.queries: list[tuple[str, tuple[object, ...]]] = []
        self.rowcount = 1
        self.fail_contains: str | None = None
        self.failure: Exception | None = None

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeCursor:
        self.queries.append((query, params))
        if self.fail_contains is not None and self.fail_contains in query:
            self.fail_contains = None
            raise self.failure or FakeIntegrityError("constraint failed")
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


class FakePool:
    def __init__(self, connection: FakeConnection | None = None) -> None:
        self.the_connection = connection or FakeConnection()
        self.closed = False
        self.opened = False

    def open(self, *, wait: bool = False) -> None:
        self.opened = wait

    @contextmanager
    def connection(self) -> Any:
        yield self.the_connection

    def close(self) -> None:
        self.closed = True


def _pooled_store(store_type: type[Any]) -> tuple[Any, FakeConnection, FakePool]:
    connection = FakeConnection()
    pool = FakePool(connection)
    database = object.__new__(PostgresDatabase)
    database._pool = pool
    return store_type(database), connection, pool


def _order() -> WorkOrder:
    return WorkOrder(
        work_order_id="wo",
        batch_id="batch",
        customer_id="tenant",
        material_name="food",
        action=ActionType.REPORT_LOSS,
    )


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


def _plan() -> OptimizationPlan:
    request = OptimizationRequest(
        customer_id="tenant",
        batches=[
            OptimizationBatch(
                batch_id="a",
                material_name="A",
                days_left=1,
                stock_qty=3,
                allowed_actions=[ActionType.REPORT_LOSS],
            ),
            OptimizationBatch(
                batch_id="b",
                material_name="B",
                days_left=2,
                stock_qty=2,
                allowed_actions=[ActionType.REPORT_LOSS],
            ),
        ],
        capacity_by_action={ActionType.REPORT_LOSS: 3},
    )
    return OptimizationPlan(plan_id="plan", request=request, result=priority_baseline(request))


def _plan_row(plan: OptimizationPlan, status: str = "pending_approval") -> tuple[object, ...]:
    executed = status == OptimizationPlanStatus.EXECUTED.value
    return (
        plan.plan_id,
        plan.request.model_dump(),
        plan.result.model_dump(),
        status,
        plan.created_at,
        "director" if executed else None,
        datetime(2026, 1, 1, tzinfo=UTC) if executed else None,
    )


def test_postgres_database_pool_lifecycle_and_dynamic_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = FakePool()
    database = PostgresDatabase(pool)
    assert pool.the_connection.commits == 1
    with database.connection() as connection:
        assert connection is pool.the_connection
    database.close()
    assert pool.closed

    created: list[tuple[str, int, int, bool]] = []

    def pool_factory(*, conninfo: str, min_size: int, max_size: int, open: bool) -> FakePool:
        created.append((conninfo, min_size, max_size, open))
        return FakePool()

    monkeypatch.setattr(
        "src.persistence.postgres.import_module",
        lambda _name: SimpleNamespace(ConnectionPool=pool_factory),
    )
    dynamic = PostgresDatabase.from_dsn("postgresql://db", min_size=2, max_size=4)
    assert created == [("postgresql://db", 2, 4, False)]
    assert dynamic._pool.opened  # type: ignore[attr-defined]  # noqa: SLF001
    dynamic.close()

    def missing(_name: str) -> object:
        raise ModuleNotFoundError

    monkeypatch.setattr("src.persistence.postgres.import_module", missing)
    with pytest.raises(RuntimeError, match="postgres"):
        PostgresDatabase.from_dsn("postgresql://db")

    sqlstate_error = RuntimeError("unique")
    sqlstate_error.sqlstate = "23505"  # type: ignore[attr-defined]
    assert _is_integrity_error(FakeIntegrityError())
    assert _is_integrity_error(sqlstate_error)
    assert not _is_integrity_error(RuntimeError())


def test_pooled_work_order_listing_and_transitions() -> None:
    store, connection, pool = _pooled_store(PostgresWorkOrderStore)
    order = _order()
    connection.the_cursor.fetchall_value = [_order_row(order)]
    assert store.list_for_customer("tenant") == [order]
    connection.the_cursor.fetchone_values.append(_order_row(order))
    started = store.transition("wo", WorkOrderStatus.IN_PROGRESS, at=order.updated_at)
    assert started.status is WorkOrderStatus.IN_PROGRESS
    store.close()
    assert not pool.closed


def test_postgres_idempotency_paths() -> None:
    store, connection, _ = _pooled_store(PostgresIdempotencyStore)
    with pytest.raises(ValueError, match="must not be empty"):
        store.claim("", "kind")
    connection.the_cursor.fetchone_values.append(("new",))
    assert store.claim("new", "kind") is None
    claim_query = connection.the_cursor.queries[-1][0]
    assert "ON CONFLICT DO NOTHING" in claim_query
    assert "RETURNING idempotency_key" in claim_query
    connection.the_cursor.fetchone_values.extend(
        [None, ("same", "kind", "completed", 200, '{"ok":true}')]
    )
    previous = store.claim("same", "kind")
    assert previous is not None and previous.status_code == 200
    store.complete("same", status_code=200, response_json="{}")
    connection.the_cursor.rowcount = 0
    with pytest.raises(KeyError, match="active idempotency"):
        store.complete("missing", status_code=200, response_json="{}")
    store.release("processing")


def test_postgres_rate_limiter_is_atomic_and_rolls_back_failures() -> None:
    database = object.__new__(PostgresDatabase)
    connection = FakeConnection()
    database._pool = FakePool(connection)
    first = PostgresRateLimiter(database, limit=2, window_seconds=60)
    second = PostgresRateLimiter(database, limit=2, window_seconds=60)

    connection.the_cursor.fetchone_values.extend([(1,), (2,), None])
    assert first.allow("client:path", now=61)
    assert second.allow("client:path", now=62)
    assert not first.allow("client:path", now=63)
    assert connection.commits == 3
    assert connection.the_cursor.queries[-1][1][2] == 2
    assert "ON CONFLICT (rate_key, window_started_at)" in connection.the_cursor.queries[-1][0]
    assert "request_count < %s" in connection.the_cursor.queries[-1][0]

    connection.the_cursor.fetchone_values.append((1,))
    assert second.allow("next-window")
    assert "CURRENT_TIMESTAMP" in connection.the_cursor.queries[-1][0]
    assert connection.the_cursor.queries[-1][1] == (60, 60, "next-window", 2)

    connection.the_cursor.fail_contains = "INSERT INTO rate_limit_windows"
    with pytest.raises(FakeIntegrityError):
        first.allow("failure", now=64)
    assert connection.rollbacks == 1

    with pytest.raises(ValueError, match="must be positive"):
        PostgresRateLimiter(database, limit=0, window_seconds=60)


def test_postgres_revision_paths() -> None:
    store, connection, _ = _pooled_store(PostgresRevisionStore)
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    session_row = (1, "operator", "tenant", "batch", timestamp, None, "pending")
    connection.the_cursor.fetchone_values.extend([(1,), session_row])
    session = store.open(
        operator_id="operator",
        customer_id="tenant",
        batch_id="batch",
        original_generated_at=timestamp,
    )
    assert session.session_id == 1
    with pytest.raises(ValueError, match="must not be empty"):
        store.attach_feedback("operator", " ", "event")
    connection.the_cursor.fetchone_values.append(None)
    with pytest.raises(KeyError, match="no pending"):
        store.attach_feedback("missing", "feedback", "event")
    processing_row = (1, "operator", "tenant", "batch", timestamp, "feedback", "processing")
    connection.the_cursor.fetchone_values.extend([(1,), processing_row])
    assert store.attach_feedback("operator", "feedback", "event").status == "processing"
    store.complete(1, timestamp)
    store.fail(1)
    connection.the_cursor.fetchone_values.append(None)
    with pytest.raises(KeyError):
        store._get_on(connection, 99)  # noqa: SLF001
    connection.the_cursor.fail_contains = "INSERT INTO revision_sessions"
    with pytest.raises(ValueError, match="already pending"):
        store.open(
            operator_id="operator",
            customer_id="tenant",
            batch_id="batch",
            original_generated_at=timestamp,
        )
    connection.the_cursor.fail_contains = "INSERT INTO revision_sessions"
    connection.the_cursor.failure = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="unavailable"):
        store.open(
            operator_id="operator",
            customer_id="tenant",
            batch_id="batch",
            original_generated_at=timestamp,
        )


def test_postgres_security_audit_paths() -> None:
    store, connection, _ = _pooled_store(PostgresSecurityAuditStore)
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    event = SecurityAuditEvent(
        event_id="event-1",
        occurred_at=timestamp,
        event_type="authorization.denied",
        subject="user-1",
        reason="customer",
        path="/api/test",
        customer_id="tenant",
        trace_id="trace",
    )
    store.record(event)
    connection.the_cursor.fetchall_value = [
        (
            event.event_id,
            event.occurred_at,
            event.event_type,
            event.subject,
            event.reason,
            event.path,
            event.customer_id,
            event.trace_id,
        )
    ]
    assert store.list_for_period(
        "tenant",
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2027, 1, 1, tzinfo=UTC),
        limit=10,
        offset=1,
    ) == [event]
    with pytest.raises(ValueError, match="timezone-aware"):
        store.list_for_period("tenant", datetime(2025, 1, 1), timestamp)
    connection.the_cursor.rowcount = 3
    assert store.purge_before(timestamp) == 3
    with pytest.raises(ValueError, match="timezone-aware"):
        store.purge_before(datetime(2026, 1, 1))


def test_postgres_optimization_paths() -> None:
    store, connection, _ = _pooled_store(PostgresOptimizationPlanStore)
    plan = _plan()
    store.save(plan)
    connection.the_cursor.fetchone_values.extend([None, _plan_row(plan)])
    assert store.get("missing") is None
    assert store.get("plan") == plan
    with pytest.raises(ValueError, match="timezone-aware"):
        store.execute("plan", approved_by="director", approved_at=datetime(2026, 1, 1))
    connection.the_cursor.fetchone_values.append(None)
    with pytest.raises(KeyError, match="not found"):
        store.execute(
            "missing", approved_by="director", approved_at=datetime(2026, 1, 1, tzinfo=UTC)
        )
    executed_row = _plan_row(plan, OptimizationPlanStatus.EXECUTED.value)
    connection.the_cursor.fetchone_values.append(executed_row)
    with pytest.raises(ValueError, match="already"):
        store.execute("plan", approved_by="director", approved_at=datetime(2026, 1, 1, tzinfo=UTC))
    connection.the_cursor.fetchone_values.extend([_plan_row(plan), (7,)])
    executed = store.execute(
        "plan", approved_by="director", approved_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    assert executed.status is OptimizationPlanStatus.EXECUTED
    connection.the_cursor.fetchone_values.append(_plan_row(plan))
    connection.the_cursor.fail_contains = "INSERT INTO decisions"
    with pytest.raises(ValueError, match="already have"):
        store.execute("plan", approved_by="director", approved_at=datetime(2026, 1, 1, tzinfo=UTC))
    connection.the_cursor.fetchone_values.append(_plan_row(plan))
    connection.the_cursor.fail_contains = "INSERT INTO decisions"
    connection.the_cursor.failure = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="unavailable"):
        store.execute("plan", approved_by="director", approved_at=datetime(2026, 1, 1, tzinfo=UTC))
