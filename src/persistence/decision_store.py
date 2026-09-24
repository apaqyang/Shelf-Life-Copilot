"""SQLite adapter for decisions and atomic approval recording."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import cast

from src.models import (
    ActionType,
    Decision,
    DecisionOutcome,
    WorkOrder,
    WorkOrderStatus,
)
from src.persistence.sqlite import SQLiteDatabase


def _require_tz(name: str, value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")


_DECISION_COLUMNS = """
    batch_id, customer_id, material_name, decided_at,
    action, outcome, savings_estimate,
    actual_savings, actual_qty, notes
"""


class DecisionStore:
    """Persist decisions and approval work orders using one SQLite connection."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        self._db = SQLiteDatabase(db_path, busy_timeout_ms=busy_timeout_ms)

    @property
    def closed(self) -> bool:
        return self._db.closed

    @property
    def schema_version(self) -> int:
        return self._db.schema_version

    @property
    def busy_timeout_ms(self) -> int:
        return self._db.busy_timeout_ms

    def __enter__(self) -> DecisionStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    def save(self, decision: Decision) -> int:
        """Insert one Decision row and return its primary-key id."""
        cur = self._db.execute(
            f"INSERT INTO decisions ({_DECISION_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _decision_values(decision),
        )
        assert cur.lastrowid is not None  # noqa: S101 - sqlite INSERT contract
        return cur.lastrowid

    def list_for_period(
        self,
        customer_id: str,
        start: datetime,
        end: datetime,
    ) -> list[Decision]:
        """Return decisions in [start, end), ordered by their UTC instant."""
        _require_tz("start", start)
        _require_tz("end", end)
        rows = self._db.fetchall(
            f"""
            SELECT {_DECISION_COLUMNS}
            FROM decisions
            WHERE customer_id = ? AND decided_at >= ? AND decided_at < ?
            ORDER BY decided_at ASC
            """,
            (
                customer_id,
                start.astimezone(UTC).isoformat(),
                end.astimezone(UTC).isoformat(),
            ),
        )
        return [_decision_from_row(row) for row in rows]

    def record_approval(
        self,
        decision: Decision,
        work_order: WorkOrder,
        *,
        idempotency_key: str,
    ) -> tuple[int, WorkOrder, bool]:
        """Atomically persist an approved decision and its work order.

        The customer/batch work-order uniqueness constraint makes repeated
        approve clicks idempotent even if the callback timestamp changes.
        Returns ``(decision_id, work_order, created)``.
        """
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

        try:
            with self._db.transaction() as connection:
                cur = connection.execute(
                    f"""
                    INSERT INTO decisions ({_DECISION_COLUMNS}, idempotency_key)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (*_decision_values(decision), idempotency_key),
                )
                assert cur.lastrowid is not None  # noqa: S101 - sqlite INSERT contract
                decision_id = cur.lastrowid
                connection.execute(
                    """
                    INSERT INTO work_orders (
                        work_order_id, decision_id, batch_id, customer_id,
                        material_name, action, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        work_order.work_order_id,
                        decision_id,
                        work_order.batch_id,
                        work_order.customer_id,
                        work_order.material_name,
                        work_order.action.value,
                        work_order.status.value,
                        work_order.created_at.astimezone(UTC).isoformat(),
                        work_order.updated_at.astimezone(UTC).isoformat(),
                    ),
                )
            return decision_id, work_order, True
        except sqlite3.IntegrityError:
            existing = self._approval_for_batch(decision.customer_id, decision.batch_id)
            if existing is None:
                raise
            return (*existing, False)

    def _approval_for_batch(self, customer_id: str, batch_id: str) -> tuple[int, WorkOrder] | None:
        row = self._db.fetchone(
            """
            SELECT w.decision_id, w.work_order_id, w.batch_id, w.customer_id,
                   w.material_name, w.action, w.status, w.created_at, w.updated_at,
                   w.actual_qty, w.actual_savings, w.completed_by, w.completed_at,
                   w.completion_source
            FROM work_orders AS w
            WHERE w.customer_id = ? AND w.batch_id = ?
            """,
            (customer_id, batch_id),
        )
        if row is None:
            return None
        return cast(int, row[0]), _work_order_from_row(row[1:])


def _decision_values(decision: Decision) -> tuple[object, ...]:
    return (
        decision.batch_id,
        decision.customer_id,
        decision.material_name,
        decision.decided_at.astimezone(UTC).isoformat(),
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
        decided_at=datetime.fromisoformat(str(row[3])),
        action=ActionType(str(row[4])),
        outcome=DecisionOutcome(str(row[5])),
        savings_estimate=cast(float, row[6]),
        actual_savings=cast(float | None, row[7]),
        actual_qty=cast(float | None, row[8]),
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
        created_at=datetime.fromisoformat(str(row[6])),
        updated_at=datetime.fromisoformat(str(row[7])),
        actual_qty=None if row[8] is None else float(str(row[8])),
        actual_savings=None if row[9] is None else float(str(row[9])),
        completed_by=None if row[10] is None else str(row[10]),
        completed_at=None if row[11] is None else datetime.fromisoformat(str(row[11])),
        completion_source=None if row[12] is None else str(row[12]),
    )
