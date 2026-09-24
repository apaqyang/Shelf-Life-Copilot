"""SQLite adapter for querying and transitioning work orders."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

from src.models import ActionType, WorkOrder, WorkOrderReceipt, WorkOrderStatus
from src.persistence.sqlite import SQLiteDatabase


class WorkOrderStore:
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

    def __enter__(self) -> WorkOrderStore:
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

    def get_for_batch(self, customer_id: str, batch_id: str) -> WorkOrder | None:
        row = self._db.fetchone(
            """
            SELECT work_order_id, batch_id, customer_id, material_name,
                   action, status, created_at, updated_at, actual_qty,
                   actual_savings, completed_by, completed_at, completion_source
            FROM work_orders
            WHERE customer_id = ? AND batch_id = ?
            """,
            (customer_id, batch_id),
        )
        return None if row is None else _from_row(row)

    def transition(
        self,
        work_order_id: str,
        status: WorkOrderStatus,
        *,
        at: datetime,
    ) -> WorkOrder:
        with self._db.transaction() as connection:
            row = connection.execute(
                """
                SELECT work_order_id, batch_id, customer_id, material_name,
                       action, status, created_at, updated_at, actual_qty,
                       actual_savings, completed_by, completed_at, completion_source
                FROM work_orders WHERE work_order_id = ?
                """,
                (work_order_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"work order {work_order_id!r} not found")
            transitioned = _from_row(row).transition_to(status, at=at)
            connection.execute(
                "UPDATE work_orders SET status = ?, updated_at = ? WHERE work_order_id = ?",
                (
                    transitioned.status.value,
                    transitioned.updated_at.astimezone(UTC).isoformat(),
                    work_order_id,
                ),
            )
        return transitioned

    def complete(self, work_order_id: str, receipt: WorkOrderReceipt) -> WorkOrder:
        """Complete an order and update its linked decision in one transaction."""
        with self._db.transaction() as connection:
            row = connection.execute(
                """
                SELECT work_order_id, batch_id, customer_id, material_name,
                       action, status, created_at, updated_at, actual_qty,
                       actual_savings, completed_by, completed_at, completion_source
                FROM work_orders WHERE work_order_id = ?
                """,
                (work_order_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"work order {work_order_id!r} not found")
            completed = _from_row(row).complete(receipt)
            connection.execute(
                """
                UPDATE work_orders
                SET status = ?, updated_at = ?, actual_qty = ?, actual_savings = ?,
                    completed_by = ?, completed_at = ?, completion_source = ?
                WHERE work_order_id = ?
                """,
                (
                    completed.status.value,
                    completed.updated_at.astimezone(UTC).isoformat(),
                    completed.actual_qty,
                    completed.actual_savings,
                    completed.completed_by,
                    completed.completed_at.astimezone(UTC).isoformat()
                    if completed.completed_at is not None
                    else None,
                    completed.completion_source,
                    work_order_id,
                ),
            )
            connection.execute(
                """
                UPDATE decisions
                SET actual_qty = ?, actual_savings = ?
                WHERE id = (SELECT decision_id FROM work_orders WHERE work_order_id = ?)
                """,
                (completed.actual_qty, completed.actual_savings, work_order_id),
            )
        return completed


def _from_row(row: tuple[object, ...]) -> WorkOrder:
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
