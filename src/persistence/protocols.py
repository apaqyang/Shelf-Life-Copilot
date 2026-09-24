"""Vendor-neutral persistence ports used by application services."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from src.models import Decision, Suggestion, WorkOrder, WorkOrderReceipt, WorkOrderStatus


@runtime_checkable
class DecisionRepository(Protocol):
    def save(self, decision: Decision) -> int: ...  # pragma: no cover

    def list_for_period(
        self, customer_id: str, start: datetime, end: datetime
    ) -> list[Decision]: ...  # pragma: no cover

    def record_approval(
        self,
        decision: Decision,
        work_order: WorkOrder,
        *,
        idempotency_key: str,
    ) -> tuple[int, WorkOrder, bool]: ...  # pragma: no cover

    def close(self) -> None: ...  # pragma: no cover


@runtime_checkable
class SuggestionRepository(Protocol):
    def save(self, suggestion: Suggestion) -> int: ...  # pragma: no cover

    def latest_for_batch(
        self, customer_id: str, batch_id: str
    ) -> Suggestion | None: ...  # pragma: no cover

    def close(self) -> None: ...  # pragma: no cover


@runtime_checkable
class WorkOrderRepository(Protocol):
    def get_for_batch(
        self, customer_id: str, batch_id: str
    ) -> WorkOrder | None: ...  # pragma: no cover

    def transition(
        self,
        work_order_id: str,
        status: WorkOrderStatus,
        *,
        at: datetime,
    ) -> WorkOrder: ...  # pragma: no cover

    def complete(
        self, work_order_id: str, receipt: WorkOrderReceipt
    ) -> WorkOrder: ...  # pragma: no cover

    def close(self) -> None: ...  # pragma: no cover
