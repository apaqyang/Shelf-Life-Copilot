"""Work-order domain model and legal state transitions."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat, model_validator

from src.models.action import ActionType


class WorkOrderStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


_TRANSITIONS: dict[WorkOrderStatus, frozenset[WorkOrderStatus]] = {
    WorkOrderStatus.PENDING: frozenset({WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.CANCELLED}),
    WorkOrderStatus.IN_PROGRESS: frozenset({WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED}),
    WorkOrderStatus.COMPLETED: frozenset(),
    WorkOrderStatus.CANCELLED: frozenset(),
}


class WorkOrderReceipt(BaseModel):
    """Auditable facts supplied when a workshop completes an order."""

    model_config = ConfigDict(frozen=True)

    actual_qty: NonNegativeFloat
    actual_savings: NonNegativeFloat
    completed_by: str = Field(min_length=1)
    completed_at: datetime
    source: str = Field(min_length=1)

    @model_validator(mode="after")
    def _require_aware_timestamp(self) -> WorkOrderReceipt:
        if self.completed_at.tzinfo is None:
            raise ValueError("completed_at must be timezone-aware")
        return self


class WorkOrder(BaseModel):
    """A traceable instruction created from an approved suggestion."""

    model_config = ConfigDict(frozen=True)

    work_order_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    batch_id: str
    customer_id: str
    material_name: str
    action: ActionType
    status: WorkOrderStatus = WorkOrderStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actual_qty: NonNegativeFloat | None = None
    actual_savings: NonNegativeFloat | None = None
    completed_by: str | None = None
    completed_at: datetime | None = None
    completion_source: str | None = None

    @model_validator(mode="after")
    def _validate_timestamps(self) -> WorkOrder:
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("work-order timestamps must be timezone-aware")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be before created_at")
        completion_values = (
            self.actual_qty,
            self.actual_savings,
            self.completed_by,
            self.completed_at,
            self.completion_source,
        )
        if self.status is WorkOrderStatus.COMPLETED:
            if any(value is None for value in completion_values):
                raise ValueError("completed work orders require a complete receipt")
            assert self.completed_at is not None  # noqa: S101 - narrowed by invariant above
            if self.completed_at.tzinfo is None:
                raise ValueError("completed_at must be timezone-aware")
        elif any(value is not None for value in completion_values):
            raise ValueError("only completed work orders may contain receipt values")
        return self

    def transition_to(self, status: WorkOrderStatus, *, at: datetime) -> WorkOrder:
        """Return a new order in `status`, rejecting illegal or stale transitions."""
        if at.tzinfo is None:
            raise ValueError("transition timestamp must be timezone-aware")
        if status is WorkOrderStatus.COMPLETED:
            raise ValueError("use complete() to attach the required receipt")
        if status not in _TRANSITIONS[self.status]:
            raise ValueError(f"illegal work-order transition: {self.status} -> {status}")
        return WorkOrder.model_validate({**self.model_dump(), "status": status, "updated_at": at})

    def complete(self, receipt: WorkOrderReceipt) -> WorkOrder:
        if WorkOrderStatus.COMPLETED not in _TRANSITIONS[self.status]:
            raise ValueError(f"illegal work-order transition: {self.status} -> completed")
        return WorkOrder.model_validate(
            {
                **self.model_dump(),
                "status": WorkOrderStatus.COMPLETED,
                "updated_at": receipt.completed_at,
                "actual_qty": receipt.actual_qty,
                "actual_savings": receipt.actual_savings,
                "completed_by": receipt.completed_by,
                "completed_at": receipt.completed_at,
                "completion_source": receipt.source,
            }
        )
