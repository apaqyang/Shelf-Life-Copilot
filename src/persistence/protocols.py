"""Vendor-neutral persistence ports used by application services."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from src.models import Decision, Suggestion, WorkOrder, WorkOrderReceipt, WorkOrderStatus
from src.optimization import OptimizationPlan
from src.persistence.idempotency_store import IdempotencyRecord
from src.persistence.revision_store import RevisionSession


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
    def get(self, work_order_id: str) -> WorkOrder | None: ...  # pragma: no cover

    def get_for_batch(
        self, customer_id: str, batch_id: str
    ) -> WorkOrder | None: ...  # pragma: no cover

    def list_for_customer(
        self, customer_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[WorkOrder]: ...  # pragma: no cover

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


@runtime_checkable
class IdempotencyRepository(Protocol):
    def claim(
        self, idempotency_key: str, request_kind: str
    ) -> IdempotencyRecord | None: ...  # pragma: no cover

    def complete(
        self, idempotency_key: str, *, status_code: int, response_json: str
    ) -> None: ...  # pragma: no cover

    def release(self, idempotency_key: str) -> None: ...  # pragma: no cover

    def close(self) -> None: ...  # pragma: no cover


@runtime_checkable
class RevisionRepository(Protocol):
    def open(
        self,
        *,
        operator_id: str,
        customer_id: str,
        batch_id: str,
        original_generated_at: datetime,
    ) -> RevisionSession: ...  # pragma: no cover

    def attach_feedback(
        self, operator_id: str, feedback: str, event_id: str
    ) -> RevisionSession: ...  # pragma: no cover

    def complete(
        self, session_id: int, revised_generated_at: datetime
    ) -> None: ...  # pragma: no cover

    def fail(self, session_id: int) -> None: ...  # pragma: no cover

    def close(self) -> None: ...  # pragma: no cover


@runtime_checkable
class OptimizationPlanRepository(Protocol):
    def save(self, plan: OptimizationPlan) -> None: ...  # pragma: no cover

    def get(self, plan_id: str) -> OptimizationPlan | None: ...  # pragma: no cover

    def execute(
        self, plan_id: str, *, approved_by: str, approved_at: datetime
    ) -> OptimizationPlan: ...  # pragma: no cover

    def close(self) -> None: ...  # pragma: no cover
