from datetime import UTC, datetime

import pytest

from src.models import ActionType
from src.optimization import (
    OptimizationBatch,
    OptimizationPlan,
    OptimizationRequest,
    priority_baseline,
)
from src.persistence import OptimizationPlanStore, WorkOrderStore


def _plan() -> OptimizationPlan:
    request = OptimizationRequest(
        customer_id="tenant",
        batches=[
            OptimizationBatch(
                batch_id="a",
                material_name="A",
                days_left=1,
                stock_qty=3,
                allowed_actions=[ActionType.REPORT_LOSS],
            ),
            OptimizationBatch(
                batch_id="b",
                material_name="B",
                days_left=2,
                stock_qty=2,
                allowed_actions=[ActionType.REPORT_LOSS],
            ),
        ],
        capacity_by_action={ActionType.REPORT_LOSS: 3},
    )
    return OptimizationPlan(plan_id="plan", request=request, result=priority_baseline(request))


def test_plan_store_persists_and_executes_work_orders_atomically(tmp_path: object) -> None:
    path = tmp_path / "plans.db"  # type: ignore[operator]
    with OptimizationPlanStore(path) as store:
        plan = _plan()
        store.save(plan)
        assert store.get("missing") is None
        assert store.get("plan") == plan
        executed = store.execute(
            "plan", approved_by="director", approved_at=datetime(2026, 1, 1, tzinfo=UTC)
        )
        assert executed.status == "executed"
        assert executed.approved_by == "director"
        with pytest.raises(ValueError, match="already"):
            store.execute(
                "plan", approved_by="director", approved_at=datetime(2026, 1, 1, tzinfo=UTC)
            )
        with pytest.raises(KeyError, match="not found"):
            store.execute(
                "missing", approved_by="director", approved_at=datetime(2026, 1, 1, tzinfo=UTC)
            )
        with pytest.raises(ValueError, match="timezone-aware"):
            store.execute("plan", approved_by="director", approved_at=datetime(2026, 1, 1))
    assert store.closed
    with WorkOrderStore(path) as orders:
        created = orders.list_for_customer("tenant")
    assert len(created) == 1
    assert created[0].batch_id == "a"


def test_plan_execution_rejects_existing_batch_order(tmp_path: object) -> None:
    path = tmp_path / "plans.db"  # type: ignore[operator]
    with OptimizationPlanStore(path) as store:
        first = _plan()
        store.save(first)
        store.execute(
            first.plan_id,
            approved_by="director",
            approved_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        second = first.model_copy(update={"plan_id": "second"})
        store.save(second)
        with pytest.raises(ValueError, match="already have"):
            store.execute(
                second.plan_id,
                approved_by="director",
                approved_at=datetime(2026, 1, 2, tzinfo=UTC),
            )
        assert store.get("second").status == "pending_approval"  # type: ignore[union-attr]
