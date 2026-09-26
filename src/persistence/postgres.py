"""PostgreSQL persistence adapters using the standard DB-API surface.

The connection is injected so the open core does not force a PostgreSQL driver
on SQLite-only installations. Production passes a psycopg connection.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from importlib import import_module
from typing import Protocol, cast
from uuid import uuid4

from src.models import (
    ActionType,
    Decision,
    DecisionOutcome,
    Suggestion,
    WorkOrder,
    WorkOrderReceipt,
    WorkOrderStatus,
)
from src.optimization import OptimizationPlan, OptimizationPlanStatus
from src.persistence.audit_store import SecurityAuditEvent, validate_audit_query
from src.persistence.idempotency_store import IdempotencyRecord
from src.persistence.revision_store import RevisionSession


class Cursor(Protocol):
    rowcount: int

    def execute(
        self, query: str, params: tuple[object, ...] = ()
    ) -> Cursor: ...  # pragma: no cover
    def fetchone(self) -> tuple[object, ...] | None: ...  # pragma: no cover
    def fetchall(self) -> list[tuple[object, ...]]: ...  # pragma: no cover


class Connection(Protocol):
    def cursor(self) -> Cursor: ...  # pragma: no cover
    def commit(self) -> None: ...  # pragma: no cover
    def rollback(self) -> None: ...  # pragma: no cover
    def close(self) -> None: ...  # pragma: no cover


class ConnectionPool(Protocol):
    def open(self, *, wait: bool = False) -> None: ...  # pragma: no cover
    def connection(self) -> AbstractContextManager[Connection]: ...  # pragma: no cover
    def close(self) -> None: ...  # pragma: no cover


class PostgresDatabase:
    """Application-owned PostgreSQL connection pool and migration boundary."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool
        with self.connection() as connection:
            run_postgres_migrations(connection)

    @classmethod
    def from_dsn(cls, dsn: str, *, min_size: int = 1, max_size: int = 10) -> PostgresDatabase:
        try:
            pool_module = import_module("psycopg_pool")
        except ModuleNotFoundError as exc:  # pragma: no cover - deployment dependency
            raise RuntimeError("PostgreSQL backend requires the 'postgres' project extra") from exc
        pool_type = pool_module.ConnectionPool
        pool = cast(
            ConnectionPool,
            pool_type(conninfo=dsn, min_size=min_size, max_size=max_size, open=False),
        )
        pool.open(wait=True)
        return cls(pool)

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        with self._pool.connection() as connection:
            yield connection

    def close(self) -> None:
        self._pool.close()


POSTGRES_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    """CREATE TABLE IF NOT EXISTS decisions (
        id BIGSERIAL PRIMARY KEY, batch_id TEXT NOT NULL, customer_id TEXT NOT NULL,
        material_name TEXT NOT NULL, decided_at TIMESTAMPTZ NOT NULL, action TEXT NOT NULL,
        outcome TEXT NOT NULL, savings_estimate DOUBLE PRECISION NOT NULL,
        actual_savings DOUBLE PRECISION, actual_qty DOUBLE PRECISION, notes TEXT,
        idempotency_key TEXT UNIQUE)""",
    """CREATE TABLE IF NOT EXISTS suggestions (
        id BIGSERIAL PRIMARY KEY, batch_id TEXT NOT NULL, customer_id TEXT NOT NULL,
        action TEXT NOT NULL, savings_estimate DOUBLE PRECISION NOT NULL, rationale TEXT NOT NULL,
        confidence DOUBLE PRECISION NOT NULL, is_standard BOOLEAN NOT NULL, llm_model TEXT NOT NULL,
        user_feedback TEXT, generated_at TIMESTAMPTZ NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS work_orders (
        work_order_id TEXT PRIMARY KEY, decision_id BIGINT NOT NULL UNIQUE REFERENCES decisions(id),
        batch_id TEXT NOT NULL, customer_id TEXT NOT NULL, material_name TEXT NOT NULL,
        action TEXT NOT NULL, status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL, actual_qty DOUBLE PRECISION,
        actual_savings DOUBLE PRECISION, completed_by TEXT, completed_at TIMESTAMPTZ,
        completion_source TEXT, UNIQUE(customer_id, batch_id))""",
    """CREATE INDEX IF NOT EXISTS idx_decisions_customer_period
        ON decisions(customer_id, decided_at)""",
    """CREATE INDEX IF NOT EXISTS idx_suggestions_lookup
        ON suggestions(customer_id, batch_id, generated_at DESC)""",
    """CREATE INDEX IF NOT EXISTS idx_work_orders_customer_status
        ON work_orders(customer_id, status, created_at DESC)""",
    """CREATE TABLE IF NOT EXISTS idempotency_records (
        idempotency_key TEXT PRIMARY KEY, request_kind TEXT NOT NULL, status TEXT NOT NULL,
        status_code INTEGER, response_json TEXT, created_at TIMESTAMPTZ NOT NULL,
        completed_at TIMESTAMPTZ)""",
    """CREATE INDEX IF NOT EXISTS idx_idempotency_created
        ON idempotency_records(request_kind, created_at)""",
    """CREATE TABLE IF NOT EXISTS revision_sessions (
        id BIGSERIAL PRIMARY KEY, operator_id TEXT NOT NULL, customer_id TEXT NOT NULL,
        batch_id TEXT NOT NULL, original_generated_at TIMESTAMPTZ NOT NULL,
        feedback TEXT, feedback_event_id TEXT, revised_generated_at TIMESTAMPTZ,
        status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL,
        UNIQUE(customer_id, batch_id, original_generated_at))""",
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_revision_operator_pending
        ON revision_sessions(operator_id) WHERE status = 'pending'""",
    """CREATE TABLE IF NOT EXISTS optimization_plans (
        plan_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, request_json JSONB NOT NULL,
        result_json JSONB NOT NULL, status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL,
        approved_by TEXT, approved_at TIMESTAMPTZ)""",
    """CREATE INDEX IF NOT EXISTS idx_optimization_plans_customer
        ON optimization_plans(customer_id, created_at DESC)""",
    """CREATE TABLE IF NOT EXISTS task_queue (
        task_id TEXT PRIMARY KEY, task_kind TEXT NOT NULL, customer_id TEXT NOT NULL,
        payload_json JSONB NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        available_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL,
        claimed_at TIMESTAMPTZ, completed_at TIMESTAMPTZ, last_error TEXT,
        dedupe_key TEXT NOT NULL UNIQUE)""",
    """CREATE INDEX IF NOT EXISTS idx_task_queue_claim
        ON task_queue(status, available_at, created_at)""",
    """CREATE TABLE IF NOT EXISTS rate_limit_windows (
        rate_key TEXT NOT NULL, window_started_at TIMESTAMPTZ NOT NULL,
        request_count INTEGER NOT NULL CHECK (request_count > 0),
        PRIMARY KEY(rate_key, window_started_at))""",
    """CREATE INDEX IF NOT EXISTS idx_rate_limit_windows_cleanup
        ON rate_limit_windows(window_started_at)""",
    """CREATE TABLE IF NOT EXISTS security_audit_events (
        event_id TEXT PRIMARY KEY, occurred_at TIMESTAMPTZ NOT NULL,
        event_type TEXT NOT NULL, subject TEXT NOT NULL, reason TEXT NOT NULL,
        path TEXT NOT NULL, customer_id TEXT, trace_id TEXT)""",
    """CREATE INDEX IF NOT EXISTS idx_security_audit_period
        ON security_audit_events(occurred_at DESC)""",
    """CREATE INDEX IF NOT EXISTS idx_security_audit_customer_period
        ON security_audit_events(customer_id, occurred_at DESC)""",
)


def run_postgres_migrations(connection: Connection) -> None:
    cursor = connection.cursor()
    try:
        for statement in POSTGRES_SCHEMA:
            cursor.execute(statement)
        for marker in (
            (8, "shared_rate_limit_windows"),
            (9, "security_audit_archive"),
        ):
            cursor.execute(
                "INSERT INTO schema_migrations(version, name) "
                "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                marker,
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _is_integrity_error(exc: Exception) -> bool:
    sqlstate = getattr(exc, "sqlstate", "")
    return exc.__class__.__name__.endswith("IntegrityError") or str(sqlstate).startswith("23")


def _security_audit_from_row(row: tuple[object, ...]) -> SecurityAuditEvent:
    return SecurityAuditEvent(
        event_id=str(row[0]),
        occurred_at=cast(datetime, row[1]),
        event_type=str(row[2]),
        subject=str(row[3]),
        reason=str(row[4]),
        path=str(row[5]),
        customer_id=None if row[6] is None else str(row[6]),
        trace_id=None if row[7] is None else str(row[7]),
    )


class _PostgresStore:
    def __init__(self, backend: Connection | PostgresDatabase) -> None:
        if isinstance(backend, PostgresDatabase):
            self._database: PostgresDatabase | None = backend
            self._connection: Connection | None = None
        else:
            self._database = None
            self._connection = backend
            run_postgres_migrations(backend)

    @contextmanager
    def _borrow(self) -> Iterator[Connection]:
        database = getattr(self, "_database", None)
        if database is not None:
            with database.connection() as connection:
                yield connection
            return
        connection = getattr(self, "_connection", None)
        assert connection is not None  # noqa: S101
        yield cast(Connection, connection)

    def close(self) -> None:
        connection = getattr(self, "_connection", None)
        if connection is not None:
            cast(Connection, connection).close()


class PostgresRateLimiter(_PostgresStore):
    """Atomic fixed-window limiter shared by every instance using one database."""

    def __init__(
        self,
        backend: Connection | PostgresDatabase,
        *,
        limit: int,
        window_seconds: int,
    ) -> None:
        if limit <= 0 or window_seconds <= 0:
            raise ValueError("rate limit and window_seconds must be positive")
        super().__init__(backend)
        self._limit = limit
        self._window_seconds = window_seconds

    def allow(self, key: str, *, now: float | None = None) -> bool:
        with self._borrow() as connection:
            cursor = connection.cursor()
            try:
                if now is None:
                    cursor.execute(
                        """WITH current_window AS (
                               SELECT to_timestamp(
                                   floor(extract(epoch FROM CURRENT_TIMESTAMP) / %s) * %s
                               ) AS started_at
                           ), expired AS (
                               DELETE FROM rate_limit_windows
                               WHERE window_started_at < (
                                   SELECT started_at FROM current_window)
                           )
                           INSERT INTO rate_limit_windows (
                               rate_key, window_started_at, request_count)
                           SELECT %s, started_at, 1 FROM current_window
                           ON CONFLICT (rate_key, window_started_at) DO UPDATE
                           SET request_count = rate_limit_windows.request_count + 1
                           WHERE rate_limit_windows.request_count < %s
                           RETURNING request_count""",
                        (
                            self._window_seconds,
                            self._window_seconds,
                            key,
                            self._limit,
                        ),
                    )
                else:
                    window_epoch = now - (now % self._window_seconds)
                    window_started_at = datetime.fromtimestamp(window_epoch, UTC)
                    cursor.execute(
                        "DELETE FROM rate_limit_windows WHERE window_started_at < %s",
                        (window_started_at,),
                    )
                    cursor.execute(
                        """INSERT INTO rate_limit_windows (
                               rate_key, window_started_at, request_count)
                           VALUES (%s, %s, 1)
                           ON CONFLICT (rate_key, window_started_at) DO UPDATE
                           SET request_count = rate_limit_windows.request_count + 1
                           WHERE rate_limit_windows.request_count < %s
                           RETURNING request_count""",
                        (key, window_started_at, self._limit),
                    )
                allowed = cursor.fetchone() is not None
                connection.commit()
                return allowed
            except Exception:
                connection.rollback()
                raise


class PostgresSecurityAuditStore(_PostgresStore):
    """PostgreSQL security archive shared across application instances."""

    def record(self, event: SecurityAuditEvent) -> None:
        with self._borrow() as connection:
            connection.cursor().execute(
                """INSERT INTO security_audit_events (
                       event_id, occurred_at, event_type, subject, reason, path,
                       customer_id, trace_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    event.event_id,
                    event.occurred_at.astimezone(UTC),
                    event.event_type,
                    event.subject,
                    event.reason,
                    event.path,
                    event.customer_id,
                    event.trace_id,
                ),
            )
            connection.commit()

    def list_for_period(
        self,
        customer_id: str,
        start: datetime,
        end: datetime,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SecurityAuditEvent]:
        validate_audit_query(start, end, limit=limit, offset=offset)
        with self._borrow() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """SELECT event_id, occurred_at, event_type, subject, reason, path,
                          customer_id, trace_id
                   FROM security_audit_events
                   WHERE customer_id = %s AND occurred_at >= %s AND occurred_at < %s
                   ORDER BY occurred_at DESC, event_id ASC
                   LIMIT %s OFFSET %s""",
                (
                    customer_id,
                    start.astimezone(UTC),
                    end.astimezone(UTC),
                    limit,
                    offset,
                ),
            )
            return [_security_audit_from_row(row) for row in cursor.fetchall()]

    def purge_before(self, cutoff: datetime) -> int:
        if cutoff.tzinfo is None:
            raise ValueError("audit retention cutoff must be timezone-aware")
        with self._borrow() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "DELETE FROM security_audit_events WHERE occurred_at < %s",
                (cutoff.astimezone(UTC),),
            )
            deleted = cursor.rowcount
            connection.commit()
            return deleted


class PostgresDecisionStore(_PostgresStore):
    def save(self, decision: Decision) -> int:
        with self._borrow() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """INSERT INTO decisions (
                    batch_id, customer_id, material_name, decided_at, action, outcome,
                    savings_estimate, actual_savings, actual_qty, notes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                _decision_values(decision),
            )
            row = cursor.fetchone()
            assert row is not None  # noqa: S101
            connection.commit()
            return int(str(row[0]))

    def list_for_period(self, customer_id: str, start: datetime, end: datetime) -> list[Decision]:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("report period boundaries must be timezone-aware")
        with self._borrow() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """SELECT batch_id, customer_id, material_name, decided_at, action, outcome,
                          savings_estimate, actual_savings, actual_qty, notes
                   FROM decisions WHERE customer_id=%s AND decided_at >= %s AND decided_at < %s
                   ORDER BY decided_at""",
                (customer_id, start.astimezone(UTC), end.astimezone(UTC)),
            )
            return [_decision_from_row(row) for row in cursor.fetchall()]

    def record_approval(
        self,
        decision: Decision,
        work_order: WorkOrder,
        *,
        idempotency_key: str,
    ) -> tuple[int, WorkOrder, bool]:
        if not decision.is_approved:
            raise ValueError("record_approval requires an approved decision")
        if not idempotency_key:
            raise ValueError("idempotency_key must not be empty")
        if (
            decision.customer_id != work_order.customer_id
            or decision.batch_id != work_order.batch_id
            or decision.action != work_order.action
        ):
            raise ValueError("decision and work order must refer to the same approval")
        with self._borrow() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """INSERT INTO decisions (
                        batch_id, customer_id, material_name, decided_at, action, outcome,
                        savings_estimate, actual_savings, actual_qty, notes, idempotency_key)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (*_decision_values(decision), idempotency_key),
                )
                row = cursor.fetchone()
                assert row is not None  # noqa: S101
                decision_id = int(str(row[0]))
                cursor.execute(
                    """INSERT INTO work_orders (
                        work_order_id, decision_id, batch_id, customer_id, material_name,
                        action, status, created_at, updated_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        work_order.work_order_id,
                        decision_id,
                        work_order.batch_id,
                        work_order.customer_id,
                        work_order.material_name,
                        work_order.action.value,
                        work_order.status.value,
                        work_order.created_at,
                        work_order.updated_at,
                    ),
                )
                connection.commit()
                return decision_id, work_order, True
            except Exception:
                connection.rollback()
                cursor = connection.cursor()
                cursor.execute(
                    """SELECT d.id, w.work_order_id, w.batch_id, w.customer_id,
                              w.material_name, w.action, w.status, w.created_at, w.updated_at
                       FROM decisions d JOIN work_orders w ON w.decision_id=d.id
                       WHERE d.idempotency_key=%s""",
                    (idempotency_key,),
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise
                return int(str(existing[0])), _work_order_from_row(existing[1:]), False


class PostgresSuggestionStore(_PostgresStore):
    def save(self, suggestion: Suggestion) -> int:
        with self._borrow() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """INSERT INTO suggestions (
                    batch_id,customer_id,action,savings_estimate,rationale,confidence,
                    is_standard,llm_model,user_feedback,generated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (
                    suggestion.batch_id,
                    suggestion.customer_id,
                    suggestion.action.value,
                    suggestion.savings_estimate,
                    suggestion.rationale,
                    suggestion.confidence,
                    suggestion.is_standard,
                    suggestion.llm_model,
                    suggestion.user_feedback,
                    suggestion.generated_at,
                ),
            )
            row = cursor.fetchone()
            assert row is not None  # noqa: S101
            connection.commit()
            return int(str(row[0]))

    def latest_for_batch(self, customer_id: str, batch_id: str) -> Suggestion | None:
        return self._latest(customer_id, batch_id, at=None)

    def latest_for_batch_at(
        self, customer_id: str, batch_id: str, at: datetime
    ) -> Suggestion | None:
        if at.tzinfo is None:
            raise ValueError("suggestion lookup timestamp must be timezone-aware")
        return self._latest(customer_id, batch_id, at=at.astimezone(UTC))

    def _latest(self, customer_id: str, batch_id: str, *, at: datetime | None) -> Suggestion | None:
        time_filter = "" if at is None else "AND generated_at <= %s"
        params: tuple[object, ...] = (
            (customer_id, batch_id) if at is None else (customer_id, batch_id, at)
        )
        with self._borrow() as connection:
            cursor = connection.cursor()
            cursor.execute(
                f"""SELECT batch_id,customer_id,action,savings_estimate,rationale,confidence,
                          is_standard,llm_model,user_feedback,generated_at
                   FROM suggestions WHERE customer_id=%s AND batch_id=%s
                   {time_filter}
                   ORDER BY generated_at DESC, id DESC LIMIT 1""",
                params,
            )
            row = cursor.fetchone()
            return None if row is None else _suggestion_from_row(row)


class PostgresWorkOrderStore(_PostgresStore):
    def get_for_batch(self, customer_id: str, batch_id: str) -> WorkOrder | None:
        return self._fetch("customer_id=%s AND batch_id=%s", (customer_id, batch_id))

    def get(self, work_order_id: str) -> WorkOrder | None:
        return self._fetch("work_order_id=%s", (work_order_id,))

    def _fetch(self, where: str, params: tuple[object, ...]) -> WorkOrder | None:
        with self._borrow() as connection:
            cursor = connection.cursor()
            cursor.execute(
                f"""SELECT work_order_id,batch_id,customer_id,material_name,action,status,
                           created_at,updated_at,actual_qty,actual_savings,completed_by,
                           completed_at,completion_source FROM work_orders WHERE {where}""",
                params,
            )
            row = cursor.fetchone()
            return None if row is None else _work_order_from_row(row)

    def list_for_customer(
        self, customer_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[WorkOrder]:
        with self._borrow() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """SELECT work_order_id,batch_id,customer_id,material_name,action,status,
                          created_at,updated_at,actual_qty,actual_savings,completed_by,
                          completed_at,completion_source FROM work_orders
                   WHERE customer_id=%s ORDER BY created_at DESC, work_order_id ASC
                   LIMIT %s OFFSET %s""",
                (customer_id, limit, offset),
            )
            return [_work_order_from_row(row) for row in cursor.fetchall()]

    def transition(self, work_order_id: str, status: WorkOrderStatus, *, at: datetime) -> WorkOrder:
        with self._borrow() as connection:
            current = self._fetch_on(connection, work_order_id)
            if current is None:
                raise KeyError(work_order_id)
            transitioned = current.transition_to(status, at=at)
            connection.cursor().execute(
                "UPDATE work_orders SET status=%s, updated_at=%s WHERE work_order_id=%s",
                (status.value, at, work_order_id),
            )
            connection.commit()
            return transitioned

    def complete(self, work_order_id: str, receipt: WorkOrderReceipt) -> WorkOrder:
        with self._borrow() as connection:
            current = self._fetch_on(connection, work_order_id)
            if current is None:
                raise KeyError(work_order_id)
            completed = current.complete(receipt)
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """UPDATE work_orders SET status=%s,updated_at=%s,actual_qty=%s,
                              actual_savings=%s,completed_by=%s,completed_at=%s,
                              completion_source=%s WHERE work_order_id=%s""",
                    (
                        completed.status.value,
                        completed.updated_at,
                        completed.actual_qty,
                        completed.actual_savings,
                        completed.completed_by,
                        completed.completed_at,
                        completed.completion_source,
                        work_order_id,
                    ),
                )
                cursor.execute(
                    """UPDATE decisions SET actual_qty=%s,actual_savings=%s
                       WHERE id=(SELECT decision_id FROM work_orders WHERE work_order_id=%s)""",
                    (completed.actual_qty, completed.actual_savings, work_order_id),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            return completed

    @staticmethod
    def _fetch_on(connection: Connection, work_order_id: str) -> WorkOrder | None:
        cursor = connection.cursor()
        cursor.execute(
            """SELECT work_order_id,batch_id,customer_id,material_name,action,status,
                      created_at,updated_at,actual_qty,actual_savings,completed_by,
                      completed_at,completion_source FROM work_orders WHERE work_order_id=%s""",
            (work_order_id,),
        )
        row = cursor.fetchone()
        return None if row is None else _work_order_from_row(row)


class PostgresIdempotencyStore(_PostgresStore):
    def claim(self, idempotency_key: str, request_kind: str) -> IdempotencyRecord | None:
        if not idempotency_key or not request_kind:
            raise ValueError("idempotency key and request kind must not be empty")
        with self._borrow() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """INSERT INTO idempotency_records (
                       idempotency_key, request_kind, status, created_at)
                   VALUES (%s, %s, 'processing', %s)
                   ON CONFLICT DO NOTHING RETURNING idempotency_key""",
                (idempotency_key, request_kind, datetime.now(UTC)),
            )
            inserted = cursor.fetchone()
            if inserted is not None:
                connection.commit()
                return None
            cursor.execute(
                """SELECT idempotency_key, request_kind, status, status_code, response_json
                   FROM idempotency_records WHERE idempotency_key=%s""",
                (idempotency_key,),
            )
            row = cursor.fetchone()
            assert row is not None  # noqa: S101
            connection.commit()
            return IdempotencyRecord(
                idempotency_key=str(row[0]),
                request_kind=str(row[1]),
                status=str(row[2]),
                status_code=None if row[3] is None else int(str(row[3])),
                response_json=None if row[4] is None else str(row[4]),
            )

    def complete(self, idempotency_key: str, *, status_code: int, response_json: str) -> None:
        with self._borrow() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """UPDATE idempotency_records SET status='completed', status_code=%s,
                          response_json=%s, completed_at=%s
                   WHERE idempotency_key=%s AND status='processing'""",
                (status_code, response_json, datetime.now(UTC), idempotency_key),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise KeyError(f"active idempotency claim {idempotency_key!r} not found")
            connection.commit()

    def release(self, idempotency_key: str) -> None:
        with self._borrow() as connection:
            connection.cursor().execute(
                "DELETE FROM idempotency_records WHERE idempotency_key=%s AND status='processing'",
                (idempotency_key,),
            )
            connection.commit()


class PostgresRevisionStore(_PostgresStore):
    def open(
        self,
        *,
        operator_id: str,
        customer_id: str,
        batch_id: str,
        original_generated_at: datetime,
    ) -> RevisionSession:
        with self._borrow() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """INSERT INTO revision_sessions (
                           operator_id, customer_id, batch_id, original_generated_at,
                           status, created_at)
                       VALUES (%s,%s,%s,%s,'pending',%s) RETURNING id""",
                    (
                        operator_id,
                        customer_id,
                        batch_id,
                        original_generated_at.astimezone(UTC),
                        datetime.now(UTC),
                    ),
                )
                row = cursor.fetchone()
                assert row is not None  # noqa: S101
                connection.commit()
            except Exception as exc:
                connection.rollback()
                if not _is_integrity_error(exc):
                    raise
                raise ValueError(
                    "a revision is already pending or this suggestion was revised"
                ) from exc
            return self._get_on(connection, int(str(row[0])))

    def attach_feedback(self, operator_id: str, feedback: str, event_id: str) -> RevisionSession:
        if not feedback.strip():
            raise ValueError("revision feedback must not be empty")
        with self._borrow() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT id FROM revision_sessions WHERE operator_id=%s AND status='pending'",
                (operator_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise KeyError("no pending revision for operator")
            session_id = int(str(row[0]))
            cursor.execute(
                """UPDATE revision_sessions SET feedback=%s, feedback_event_id=%s,
                          status='processing' WHERE id=%s""",
                (feedback, event_id, session_id),
            )
            connection.commit()
            return self._get_on(connection, session_id)

    def complete(self, session_id: int, revised_generated_at: datetime) -> None:
        with self._borrow() as connection:
            connection.cursor().execute(
                """UPDATE revision_sessions SET status='completed', revised_generated_at=%s
                   WHERE id=%s""",
                (revised_generated_at.astimezone(UTC), session_id),
            )
            connection.commit()

    def fail(self, session_id: int) -> None:
        with self._borrow() as connection:
            connection.cursor().execute(
                "UPDATE revision_sessions SET status='failed' WHERE id=%s",
                (session_id,),
            )
            connection.commit()

    @staticmethod
    def _get_on(connection: Connection, session_id: int) -> RevisionSession:
        cursor = connection.cursor()
        cursor.execute(
            """SELECT id, operator_id, customer_id, batch_id, original_generated_at,
                      feedback, status FROM revision_sessions WHERE id=%s""",
            (session_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise KeyError(session_id)
        return RevisionSession(
            session_id=int(str(row[0])),
            operator_id=str(row[1]),
            customer_id=str(row[2]),
            batch_id=str(row[3]),
            original_generated_at=cast(datetime, row[4]),
            feedback=None if row[5] is None else str(row[5]),
            status=str(row[6]),
        )


class PostgresOptimizationPlanStore(_PostgresStore):
    def save(self, plan: OptimizationPlan) -> None:
        with self._borrow() as connection:
            connection.cursor().execute(
                """INSERT INTO optimization_plans
                   (plan_id, customer_id, request_json, result_json, status, created_at)
                   VALUES (%s,%s,%s::jsonb,%s::jsonb,%s,%s)""",
                (
                    plan.plan_id,
                    plan.request.customer_id,
                    plan.request.model_dump_json(),
                    plan.result.model_dump_json(),
                    plan.status.value,
                    plan.created_at,
                ),
            )
            connection.commit()

    def get(self, plan_id: str) -> OptimizationPlan | None:
        with self._borrow() as connection:
            row = self._get_row(connection, plan_id)
            return None if row is None else _optimization_from_row(row)

    def execute(self, plan_id: str, *, approved_by: str, approved_at: datetime) -> OptimizationPlan:
        if approved_at.tzinfo is None:
            raise ValueError("approved_at must be timezone-aware")
        with self._borrow() as connection:
            try:
                row = self._get_row(connection, plan_id, for_update=True)
                if row is None:
                    raise KeyError(f"optimization plan {plan_id!r} not found")
                plan = _optimization_from_row(row)
                if plan.status is not OptimizationPlanStatus.PENDING_APPROVAL:
                    raise ValueError("optimization plan has already been executed")
                batches = {batch.batch_id: batch for batch in plan.request.batches}
                cursor = connection.cursor()
                for assignment in plan.result.assignments:
                    if assignment.allocated_qty == 0:
                        continue
                    batch = batches[assignment.batch_id]
                    cursor.execute(
                        """INSERT INTO decisions
                           (batch_id,customer_id,material_name,decided_at,action,outcome,
                            savings_estimate,notes,idempotency_key)
                           VALUES (%s,%s,%s,%s,%s,'approved',0,%s,%s) RETURNING id""",
                        (
                            batch.batch_id,
                            plan.request.customer_id,
                            batch.material_name or batch.batch_id,
                            approved_at,
                            assignment.action.value,
                            f"optimization plan {plan_id}; allocated_qty={assignment.allocated_qty}",
                            f"optimization:{plan_id}:{batch.batch_id}",
                        ),
                    )
                    decision_row = cursor.fetchone()
                    assert decision_row is not None  # noqa: S101
                    cursor.execute(
                        """INSERT INTO work_orders
                           (work_order_id,decision_id,batch_id,customer_id,material_name,
                            action,status,created_at,updated_at)
                           VALUES (%s,%s,%s,%s,%s,%s,'pending',%s,%s)""",
                        (
                            str(uuid4()),
                            decision_row[0],
                            batch.batch_id,
                            plan.request.customer_id,
                            batch.material_name or batch.batch_id,
                            assignment.action.value,
                            approved_at,
                            approved_at,
                        ),
                    )
                cursor.execute(
                    """UPDATE optimization_plans SET status=%s, approved_by=%s,
                              approved_at=%s WHERE plan_id=%s""",
                    (OptimizationPlanStatus.EXECUTED.value, approved_by, approved_at, plan_id),
                )
                connection.commit()
            except (KeyError, ValueError):
                connection.rollback()
                raise
            except Exception as exc:
                connection.rollback()
                if not _is_integrity_error(exc):
                    raise
                raise ValueError("one or more batches already have a work order") from exc
            return plan.model_copy(
                update={
                    "status": OptimizationPlanStatus.EXECUTED,
                    "approved_by": approved_by,
                    "approved_at": approved_at,
                }
            )

    @staticmethod
    def _get_row(
        connection: Connection, plan_id: str, *, for_update: bool = False
    ) -> tuple[object, ...] | None:
        cursor = connection.cursor()
        suffix = " FOR UPDATE" if for_update else ""
        cursor.execute(
            """SELECT plan_id, request_json, result_json, status, created_at,
                      approved_by, approved_at FROM optimization_plans WHERE plan_id=%s"""
            + suffix,
            (plan_id,),
        )
        return cursor.fetchone()


def _optimization_from_row(row: tuple[object, ...]) -> OptimizationPlan:
    def json_value(value: object) -> object:
        return json.loads(value) if isinstance(value, str) else value

    return OptimizationPlan.model_validate(
        {
            "plan_id": row[0],
            "request": json_value(row[1]),
            "result": json_value(row[2]),
            "status": row[3],
            "created_at": row[4],
            "approved_by": row[5],
            "approved_at": row[6],
        }
    )


def _decision_values(decision: Decision) -> tuple[object, ...]:
    return (
        decision.batch_id,
        decision.customer_id,
        decision.material_name,
        decision.decided_at,
        decision.action.value,
        decision.outcome.value,
        decision.savings_estimate,
        decision.actual_savings,
        decision.actual_qty,
        decision.notes,
    )


def _decision_from_row(row: tuple[object, ...]) -> Decision:
    return Decision(
        batch_id=str(row[0]),
        customer_id=str(row[1]),
        material_name=str(row[2]),
        decided_at=cast(datetime, row[3]),
        action=ActionType(str(row[4])),
        outcome=DecisionOutcome(str(row[5])),
        savings_estimate=float(str(row[6])),
        actual_savings=None if row[7] is None else float(str(row[7])),
        actual_qty=None if row[8] is None else float(str(row[8])),
        notes=None if row[9] is None else str(row[9]),
    )


def _work_order_from_row(row: tuple[object, ...]) -> WorkOrder:
    return WorkOrder(
        work_order_id=str(row[0]),
        batch_id=str(row[1]),
        customer_id=str(row[2]),
        material_name=str(row[3]),
        action=ActionType(str(row[4])),
        status=WorkOrderStatus(str(row[5])),
        created_at=cast(datetime, row[6]),
        updated_at=cast(datetime, row[7]),
        actual_qty=None if len(row) < 9 or row[8] is None else float(str(row[8])),
        actual_savings=None if len(row) < 10 or row[9] is None else float(str(row[9])),
        completed_by=None if len(row) < 11 or row[10] is None else str(row[10]),
        completed_at=None if len(row) < 12 or row[11] is None else cast(datetime, row[11]),
        completion_source=None if len(row) < 13 or row[12] is None else str(row[12]),
    )


def _suggestion_from_row(row: tuple[object, ...]) -> Suggestion:
    return Suggestion(
        batch_id=str(row[0]),
        customer_id=str(row[1]),
        action=ActionType(str(row[2])),
        savings_estimate=float(str(row[3])),
        rationale=str(row[4]),
        confidence=float(str(row[5])),
        is_standard=bool(row[6]),
        llm_model=str(row[7]),
        user_feedback=None if row[8] is None else str(row[8]),
        generated_at=cast(datetime, row[9]),
    )
