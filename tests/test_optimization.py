from __future__ import annotations

from datetime import datetime

import pytest

from src.models import ActionType
from src.optimization import (
    OptimizationBatch,
    OptimizationPlan,
    OptimizationPlanStatus,
    OptimizationRequest,
    default_evaluation_cases,
    evaluate_optimizer,
    priority_baseline,
)


def test_priority_baseline_is_deterministic_and_capacity_bounded() -> None:
    request = OptimizationRequest(
        customer_id="demo",
        batches=[
            OptimizationBatch(
                batch_id="later", days_left=5, stock_qty=8, allowed_actions=[ActionType.REPORT_LOSS]
            ),
            OptimizationBatch(
                batch_id="urgent",
                days_left=1,
                stock_qty=7,
                allowed_actions=[ActionType.REPORT_LOSS],
            ),
        ],
        capacity_by_action={ActionType.REPORT_LOSS: 10},
    )
    result = priority_baseline(request)
    assert [a.batch_id for a in result.assignments] == ["urgent", "later"]
    assert [a.allocated_qty for a in result.assignments] == [7, 3]
    assert result.coverage_rate == 10 / 15


def test_zero_stock_has_full_coverage() -> None:
    request = OptimizationRequest(
        customer_id="demo",
        batches=[
            OptimizationBatch(
                batch_id="a", days_left=1, stock_qty=0, allowed_actions=[ActionType.REPORT_LOSS]
            ),
            OptimizationBatch(
                batch_id="b", days_left=2, stock_qty=0, allowed_actions=[ActionType.REPORT_LOSS]
            ),
        ],
        capacity_by_action={},
    )
    assert priority_baseline(request).coverage_rate == 1


def test_baseline_selects_an_allowed_action_with_available_capacity() -> None:
    request = OptimizationRequest(
        customer_id="demo",
        batches=[
            OptimizationBatch(
                batch_id="a",
                days_left=1,
                stock_qty=2,
                allowed_actions=[ActionType.TRANSFORM, ActionType.REPORT_LOSS],
            ),
            OptimizationBatch(
                batch_id="b",
                days_left=2,
                stock_qty=2,
                allowed_actions=[ActionType.TRANSFORM, ActionType.REPORT_LOSS],
            ),
        ],
        capacity_by_action={ActionType.REPORT_LOSS: 4},
    )
    result = priority_baseline(request)
    assert {assignment.action for assignment in result.assignments} == {ActionType.REPORT_LOSS}
    assert result.coverage_rate == 1


def test_optimizer_evaluation_gate_passes_sanitized_cases() -> None:
    gate = evaluate_optimizer(default_evaluation_cases())
    assert gate.passed is True
    assert gate.case_count == 2
    assert gate.deterministic is True
    assert gate.capacity_safe is True
    assert gate.assignment_complete is True
    assert gate.minimum_coverage_rate == 0.65
    assert gate.observed_minimum_coverage == 10 / 15
    assert evaluate_optimizer(default_evaluation_cases(), minimum_coverage_rate=0.9).passed is False
    with pytest.raises(ValueError, match="must not be empty"):
        evaluate_optimizer([])


def test_plan_enforces_complete_timezone_aware_approval() -> None:
    request = default_evaluation_cases()[0]
    result = priority_baseline(request)
    with pytest.raises(ValueError, match="require approval"):
        OptimizationPlan(
            request=request,
            result=result,
            status=OptimizationPlanStatus.EXECUTED,
        )
    with pytest.raises(ValueError, match="cannot have"):
        OptimizationPlan(request=request, result=result, approved_by="director")
    with pytest.raises(ValueError, match="timezone-aware"):
        OptimizationPlan(
            request=request,
            result=result,
            status=OptimizationPlanStatus.EXECUTED,
            approved_by="director",
            approved_at=datetime(2026, 1, 1),
        )
