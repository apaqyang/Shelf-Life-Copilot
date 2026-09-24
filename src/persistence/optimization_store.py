"""Durable optimization plans with an explicit human-approval transition."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from uuid import uuid4

from src.optimization import OptimizationPlan, OptimizationPlanStatus
from src.persistence.sqlite import SQLiteDatabase


class OptimizationPlanStore:
    def __init__(self, db_path: Path | str) -> None:
        self._db = SQLiteDatabase(db_path)

    @property
    def closed(self) -> bool:
        return self._db.closed

    def __enter__(self) -> OptimizationPlanStore:
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

    def save(self, plan: OptimizationPlan) -> None:
        self._db.execute(
            """INSERT INTO optimization_plans
               (plan_id, customer_id, request_json, result_json, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                plan.plan_id,
                plan.request.customer_id,
                plan.request.model_dump_json(),
                plan.result.model_dump_json(),
                plan.status.value,
                plan.created_at.astimezone(UTC).isoformat(),
            ),
        )

    def get(self, plan_id: str) -> OptimizationPlan | None:
        row = self._db.fetchone(
            """SELECT plan_id, request_json, result_json, status, created_at,
                      approved_by, approved_at
               FROM optimization_plans WHERE plan_id = ?""",
            (plan_id,),
        )
        return None if row is None else _from_row(row)

    def execute(self, plan_id: str, *, approved_by: str, approved_at: datetime) -> OptimizationPlan:
        if approved_at.tzinfo is None:
            raise ValueError("approved_at must be timezone-aware")
        try:
            with self._db.transaction() as connection:
                row = connection.execute(
                    """SELECT plan_id, request_json, result_json, status, created_at,
                              approved_by, approved_at
                       FROM optimization_plans WHERE plan_id = ?""",
                    (plan_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"optimization plan {plan_id!r} not found")
                plan = _from_row(row)
                if plan.status is not OptimizationPlanStatus.PENDING_APPROVAL:
                    raise ValueError("optimization plan has already been executed")
                batches = {batch.batch_id: batch for batch in plan.request.batches}
                timestamp = approved_at.astimezone(UTC).isoformat()
                for assignment in plan.result.assignments:
                    if assignment.allocated_qty == 0:
                        continue
                    batch = batches[assignment.batch_id]
                    decision = connection.execute(
                        """INSERT INTO decisions
                           (batch_id, customer_id, material_name, decided_at, action,
                            outcome, savings_estimate, notes, idempotency_key)
                           VALUES (?, ?, ?, ?, ?, 'approved', 0, ?, ?)""",
                        (
                            batch.batch_id,
                            plan.request.customer_id,
                            batch.material_name or batch.batch_id,
                            timestamp,
                            assignment.action.value,
                            f"optimization plan {plan_id}; allocated_qty={assignment.allocated_qty}",
                            f"optimization:{plan_id}:{batch.batch_id}",
                        ),
                    )
                    assert decision.lastrowid is not None  # noqa: S101
                    connection.execute(
                        """INSERT INTO work_orders
                           (work_order_id, decision_id, batch_id, customer_id, material_name,
                            action, status, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                        (
                            str(uuid4()),
                            decision.lastrowid,
                            batch.batch_id,
                            plan.request.customer_id,
                            batch.material_name or batch.batch_id,
                            assignment.action.value,
                            timestamp,
                            timestamp,
                        ),
                    )
                connection.execute(
                    """UPDATE optimization_plans
                       SET status = ?, approved_by = ?, approved_at = ? WHERE plan_id = ?""",
                    (
                        OptimizationPlanStatus.EXECUTED.value,
                        approved_by,
                        timestamp,
                        plan_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("one or more batches already have a work order") from exc
        return plan.model_copy(
            update={
                "status": OptimizationPlanStatus.EXECUTED,
                "approved_by": approved_by,
                "approved_at": approved_at,
            }
        )


def _from_row(row: tuple[object, ...]) -> OptimizationPlan:
    return OptimizationPlan.model_validate(
        {
            "plan_id": row[0],
            "request": json.loads(str(row[1])),
            "result": json.loads(str(row[2])),
            "status": row[3],
            "created_at": row[4],
            "approved_by": row[5],
            "approved_at": row[6],
        }
    )
