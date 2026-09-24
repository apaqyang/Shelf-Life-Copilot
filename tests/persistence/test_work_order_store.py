"""WorkOrderStore query and state-transition behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.models import (
    ActionType,
    Decision,
    DecisionOutcome,
    WorkOrder,
    WorkOrderReceipt,
    WorkOrderStatus,
)
from src.persistence import (
    DecisionStore,
    WorkOrderRepository,
    WorkOrderStore,
)


def _seed(path: Path) -> WorkOrder:
    timestamp = datetime(2026, 9, 23, 8, tzinfo=UTC)
    decision = Decision(
        batch_id="A-001",
        customer_id="customerA",
        material_name="冷冻虾仁",
        decided_at=timestamp,
        action=ActionType.TRANSFORM,
        outcome=DecisionOutcome.APPROVED,
        savings_estimate=100,
    )
    order = WorkOrder(
        work_order_id="WO-1",
        batch_id=decision.batch_id,
        customer_id=decision.customer_id,
        material_name=decision.material_name,
        action=decision.action,
        created_at=timestamp,
        updated_at=timestamp,
    )
    with DecisionStore(path) as decisions:
        decisions.record_approval(decision, order, idempotency_key="event-1")
    return order


def test_query_transition_and_persistence(tmp_path: Path) -> None:
    path = tmp_path / "orders.db"
    original = _seed(path)
    with WorkOrderStore(path) as store:
        assert isinstance(store, WorkOrderRepository)
        assert store.closed is False
        assert store.get_for_batch("missing", "missing") is None
        assert store.get_for_batch("customerA", "A-001") == original
        started = store.transition(
            "WO-1",
            WorkOrderStatus.IN_PROGRESS,
            at=original.created_at + timedelta(hours=1),
        )
        completed = store.complete(
            "WO-1",
            WorkOrderReceipt(
                actual_qty=80,
                actual_savings=90,
                completed_by="operator-1",
                completed_at=original.created_at + timedelta(hours=2),
                source="manual_api",
            ),
        )
        assert started.status is WorkOrderStatus.IN_PROGRESS
        assert completed.status is WorkOrderStatus.COMPLETED
        assert completed.completed_by == "operator-1"
    assert store.closed is True
    with WorkOrderStore(path) as reopened:
        assert reopened.get_for_batch("customerA", "A-001") == completed
    with DecisionStore(path) as decisions:
        rows = decisions.list_for_period(
            "customerA",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2027, 1, 1, tzinfo=UTC),
        )
        assert rows[0].actual_qty == 80
        assert rows[0].actual_savings == 90


def test_missing_and_illegal_transition_roll_back(tmp_path: Path) -> None:
    path = tmp_path / "orders.db"
    original = _seed(path)
    with WorkOrderStore(path) as store:
        with pytest.raises(KeyError, match="missing"):
            store.transition("missing", WorkOrderStatus.IN_PROGRESS, at=original.updated_at)
        with pytest.raises(ValueError, match="use complete"):
            store.transition("WO-1", WorkOrderStatus.COMPLETED, at=original.updated_at)
        assert store.get_for_batch("customerA", "A-001") == original


def test_complete_missing_or_pending_order_rolls_back(tmp_path: Path) -> None:
    path = tmp_path / "orders.db"
    original = _seed(path)
    receipt = WorkOrderReceipt(
        actual_qty=1,
        actual_savings=2,
        completed_by="operator",
        completed_at=original.created_at + timedelta(hours=1),
        source="api",
    )
    with WorkOrderStore(path) as store:
        with pytest.raises(KeyError, match="missing"):
            store.complete("missing", receipt)
        with pytest.raises(ValueError, match="illegal"):
            store.complete("WO-1", receipt)
        assert store.get_for_batch("customerA", "A-001") == original
