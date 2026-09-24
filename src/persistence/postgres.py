"""PostgreSQL persistence adapters using the standard DB-API surface.

The connection is injected so the open core does not force a PostgreSQL driver
on SQLite-only installations. Production passes a psycopg connection.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, cast

from src.models import (
    ActionType,
    Decision,
    DecisionOutcome,
    Suggestion,
    WorkOrder,
    WorkOrderReceipt,
    WorkOrderStatus,
)


class Cursor(Protocol):
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
)


def run_postgres_migrations(connection: Connection) -> None:
    cursor = connection.cursor()
    try:
        for statement in POSTGRES_SCHEMA:
            cursor.execute(statement)
        cursor.execute(
            "INSERT INTO schema_migrations(version, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (1, "baseline"),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


class PostgresDecisionStore:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        run_postgres_migrations(connection)

    def close(self) -> None:
        self._connection.close()

    def save(self, decision: Decision) -> int:
        cursor = self._connection.cursor()
        cursor.execute(
            """INSERT INTO decisions (
                batch_id, customer_id, material_name, decided_at, action, outcome,
                savings_estimate, actual_savings, actual_qty, notes)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            _decision_values(decision),
        )
        row = cursor.fetchone()
        assert row is not None  # noqa: S101
        self._connection.commit()
        return int(str(row[0]))

    def list_for_period(self, customer_id: str, start: datetime, end: datetime) -> list[Decision]:
        cursor = self._connection.cursor()
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
        cursor = self._connection.cursor()
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
            self._connection.commit()
            return decision_id, work_order, True
        except Exception:
            self._connection.rollback()
            cursor = self._connection.cursor()
            cursor.execute(
                """SELECT d.id, w.work_order_id, w.batch_id, w.customer_id, w.material_name,
                          w.action, w.status, w.created_at, w.updated_at
                   FROM decisions d JOIN work_orders w ON w.decision_id=d.id
                   WHERE d.idempotency_key=%s""",
                (idempotency_key,),
            )
            existing = cursor.fetchone()
            if existing is None:
                raise
            return int(str(existing[0])), _work_order_from_row(existing[1:]), False


class PostgresSuggestionStore:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        run_postgres_migrations(connection)

    def close(self) -> None:
        self._connection.close()

    def save(self, suggestion: Suggestion) -> int:
        cursor = self._connection.cursor()
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
        self._connection.commit()
        return int(str(row[0]))

    def latest_for_batch(self, customer_id: str, batch_id: str) -> Suggestion | None:
        cursor = self._connection.cursor()
        cursor.execute(
            """SELECT batch_id,customer_id,action,savings_estimate,rationale,confidence,
                      is_standard,llm_model,user_feedback,generated_at
               FROM suggestions WHERE customer_id=%s AND batch_id=%s
               ORDER BY generated_at DESC, id DESC LIMIT 1""",
            (customer_id, batch_id),
        )
        row = cursor.fetchone()
        return None if row is None else _suggestion_from_row(row)


class PostgresWorkOrderStore:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        run_postgres_migrations(connection)

    def close(self) -> None:
        self._connection.close()

    def get_for_batch(self, customer_id: str, batch_id: str) -> WorkOrder | None:
        return self._fetch("customer_id=%s AND batch_id=%s", (customer_id, batch_id))

    def get(self, work_order_id: str) -> WorkOrder | None:
        return self._fetch("work_order_id=%s", (work_order_id,))

    def _fetch(self, where: str, params: tuple[object, ...]) -> WorkOrder | None:
        cursor = self._connection.cursor()
        cursor.execute(
            f"""SELECT work_order_id,batch_id,customer_id,material_name,action,status,
                       created_at,updated_at,actual_qty,actual_savings,completed_by,
                       completed_at,completion_source FROM work_orders WHERE {where}""",
            params,
        )
        row = cursor.fetchone()
        return None if row is None else _work_order_from_row(row)

    def transition(self, work_order_id: str, status: WorkOrderStatus, *, at: datetime) -> WorkOrder:
        current = self.get(work_order_id)
        if current is None:
            raise KeyError(work_order_id)
        transitioned = current.transition_to(status, at=at)
        self._connection.cursor().execute(
            "UPDATE work_orders SET status=%s, updated_at=%s WHERE work_order_id=%s",
            (status.value, at, work_order_id),
        )
        self._connection.commit()
        return transitioned

    def complete(self, work_order_id: str, receipt: WorkOrderReceipt) -> WorkOrder:
        current = self.get(work_order_id)
        if current is None:
            raise KeyError(work_order_id)
        completed = current.complete(receipt)
        cursor = self._connection.cursor()
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
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return completed


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
