"""Work-order domain state-machine tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from src.models import ActionType, WorkOrder, WorkOrderReceipt, WorkOrderStatus


def _order(**overrides: object) -> WorkOrder:
    created = datetime(2026, 9, 23, 8, tzinfo=UTC)
    values: dict[str, object] = {
        "work_order_id": "WO-1",
        "batch_id": "A-001",
        "customer_id": "customerA",
        "material_name": "冷冻虾仁",
        "action": ActionType.TRANSFORM,
        "created_at": created,
        "updated_at": created,
    }
    values.update(overrides)
    return WorkOrder(**values)  # type: ignore[arg-type]


def test_defaults_create_pending_order_with_identifier() -> None:
    order = WorkOrder(
        batch_id="A-001",
        customer_id="customerA",
        material_name="冷冻虾仁",
        action=ActionType.TRANSFORM,
    )
    assert order.work_order_id
    assert order.status is WorkOrderStatus.PENDING
    assert order.created_at.tzinfo is not None


def test_legal_transition_chain_returns_new_immutable_models() -> None:
    order = _order()
    started = order.transition_to(
        WorkOrderStatus.IN_PROGRESS,
        at=order.created_at + timedelta(hours=1),
    )
    completed = started.complete(
        WorkOrderReceipt(
            actual_qty=10,
            actual_savings=100,
            completed_by="operator-1",
            completed_at=order.created_at + timedelta(hours=2),
            source="manual_api",
        )
    )
    assert order.status is WorkOrderStatus.PENDING
    assert started.status is WorkOrderStatus.IN_PROGRESS
    assert completed.status is WorkOrderStatus.COMPLETED
    assert completed.actual_savings == 100


def test_pending_order_can_be_cancelled() -> None:
    order = _order()
    cancelled = order.transition_to(
        WorkOrderStatus.CANCELLED,
        at=order.created_at + timedelta(minutes=1),
    )
    assert cancelled.status is WorkOrderStatus.CANCELLED


@pytest.mark.parametrize(
    ("status", "target"),
    [
        (WorkOrderStatus.CANCELLED, WorkOrderStatus.IN_PROGRESS),
        (WorkOrderStatus.PENDING, WorkOrderStatus.PENDING),
    ],
)
def test_illegal_transition_is_rejected(status: WorkOrderStatus, target: WorkOrderStatus) -> None:
    order = _order(status=status)
    with pytest.raises(ValueError, match="illegal"):
        order.transition_to(target, at=order.updated_at)


def test_naive_or_reversed_timestamps_are_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        _order(created_at=datetime(2026, 9, 23))
    with pytest.raises(ValidationError, match="before"):
        _order(updated_at=datetime(2026, 9, 22, tzinfo=UTC))
    with pytest.raises(ValueError, match="timezone-aware"):
        _order().transition_to(WorkOrderStatus.IN_PROGRESS, at=datetime(2026, 9, 24))


def test_completion_requires_receipt_and_in_progress_state() -> None:
    order = _order()
    with pytest.raises(ValueError, match="use complete"):
        order.transition_to(WorkOrderStatus.COMPLETED, at=order.updated_at)
    receipt = WorkOrderReceipt(
        actual_qty=1,
        actual_savings=2,
        completed_by="operator",
        completed_at=order.updated_at,
        source="api",
    )
    with pytest.raises(ValueError, match="illegal"):
        order.complete(receipt)
    with pytest.raises(ValidationError, match="timezone-aware"):
        WorkOrderReceipt(
            actual_qty=1,
            actual_savings=2,
            completed_by="operator",
            completed_at=datetime(2026, 9, 24),
            source="api",
        )


def test_completion_fields_are_all_or_nothing() -> None:
    with pytest.raises(ValidationError, match="complete receipt"):
        _order(status=WorkOrderStatus.COMPLETED)
    with pytest.raises(ValidationError, match="only completed"):
        _order(actual_qty=1)
    with pytest.raises(ValidationError, match="timezone-aware"):
        _order(
            status=WorkOrderStatus.COMPLETED,
            actual_qty=1,
            actual_savings=2,
            completed_by="operator",
            completed_at=datetime(2026, 9, 24),
            completion_source="api",
        )


def test_frozen() -> None:
    order = _order()
    with pytest.raises(ValidationError):
        order.status = WorkOrderStatus.COMPLETED  # type: ignore[misc]
