"""Independent contracts for evaluated cross-batch optimization experiments."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models import ActionType


class OptimizationBatch(BaseModel):
    model_config = ConfigDict(frozen=True)
    batch_id: str
    material_name: str = ""
    days_left: int
    stock_qty: float = Field(ge=0)
    allowed_actions: list[ActionType] = Field(min_length=1)


class OptimizationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    customer_id: str
    batches: list[OptimizationBatch] = Field(min_length=2)
    capacity_by_action: dict[ActionType, float]


class OptimizationAssignment(BaseModel):
    model_config = ConfigDict(frozen=True)
    batch_id: str
    action: ActionType
    allocated_qty: float = Field(ge=0)


class OptimizationResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    assignments: list[OptimizationAssignment]
    coverage_rate: float = Field(ge=0, le=1)


class OptimizationGate(BaseModel):
    model_config = ConfigDict(frozen=True)
    passed: bool
    case_count: int
    deterministic: bool
    capacity_safe: bool
    assignment_complete: bool
    minimum_coverage_rate: float = Field(ge=0, le=1)
    observed_minimum_coverage: float = Field(ge=0, le=1)


class OptimizationPlanStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    EXECUTED = "executed"


class OptimizationPlan(BaseModel):
    model_config = ConfigDict(frozen=True)
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    request: OptimizationRequest
    result: OptimizationResult
    status: OptimizationPlanStatus = OptimizationPlanStatus.PENDING_APPROVAL
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    approved_by: str | None = None
    approved_at: datetime | None = None

    @model_validator(mode="after")
    def _approval_is_complete(self) -> OptimizationPlan:
        values = (self.approved_by, self.approved_at)
        if self.status is OptimizationPlanStatus.EXECUTED and any(v is None for v in values):
            raise ValueError("executed plans require approval metadata")
        if self.status is OptimizationPlanStatus.PENDING_APPROVAL and any(
            v is not None for v in values
        ):
            raise ValueError("pending plans cannot have approval metadata")
        if self.approved_at is not None and self.approved_at.tzinfo is None:
            raise ValueError("approved_at must be timezone-aware")
        return self


def priority_baseline(request: OptimizationRequest) -> OptimizationResult:
    """Deterministic earliest-expiry allocation used as the quality floor."""
    remaining = dict(request.capacity_by_action)
    assignments: list[OptimizationAssignment] = []
    allocated = 0.0
    total = sum(batch.stock_qty for batch in request.batches)
    for batch in sorted(request.batches, key=lambda item: (item.days_left, item.batch_id)):
        action = max(batch.allowed_actions, key=lambda candidate: remaining.get(candidate, 0.0))
        quantity = min(batch.stock_qty, remaining.get(action, 0.0))
        remaining[action] = remaining.get(action, 0.0) - quantity
        allocated += quantity
        assignments.append(
            OptimizationAssignment(
                batch_id=batch.batch_id,
                action=action,
                allocated_qty=quantity,
            )
        )
    return OptimizationResult(
        assignments=assignments,
        coverage_rate=1.0 if total == 0 else allocated / total,
    )


def evaluate_optimizer(
    cases: list[OptimizationRequest], *, minimum_coverage_rate: float = 0.65
) -> OptimizationGate:
    """Gate the optimizer on determinism, completeness and capacity safety."""
    if not cases:
        raise ValueError("evaluation cases must not be empty")
    deterministic = True
    capacity_safe = True
    assignment_complete = True
    coverage_rates: list[float] = []
    for case in cases:
        first = priority_baseline(case)
        coverage_rates.append(first.coverage_rate)
        deterministic = deterministic and first == priority_baseline(case)
        assignment_complete = assignment_complete and {
            item.batch_id for item in first.assignments
        } == {item.batch_id for item in case.batches}
        used: dict[ActionType, float] = {}
        for item in first.assignments:
            used[item.action] = used.get(item.action, 0) + item.allocated_qty
        capacity_safe = capacity_safe and all(
            quantity <= case.capacity_by_action.get(action, 0) for action, quantity in used.items()
        )
    observed_minimum = min(coverage_rates)
    passed = (
        deterministic
        and capacity_safe
        and assignment_complete
        and observed_minimum >= minimum_coverage_rate
    )
    return OptimizationGate(
        passed=passed,
        case_count=len(cases),
        deterministic=deterministic,
        capacity_safe=capacity_safe,
        assignment_complete=assignment_complete,
        minimum_coverage_rate=minimum_coverage_rate,
        observed_minimum_coverage=observed_minimum,
    )


def default_evaluation_cases() -> list[OptimizationRequest]:
    """Sanitized edge cases used as the startup quality gate."""
    action = ActionType.REPORT_LOSS
    return [
        OptimizationRequest(
            customer_id="eval",
            batches=[
                OptimizationBatch(
                    batch_id="urgent", days_left=-1, stock_qty=7, allowed_actions=[action]
                ),
                OptimizationBatch(
                    batch_id="later", days_left=30, stock_qty=8, allowed_actions=[action]
                ),
            ],
            capacity_by_action={action: 10},
        ),
        OptimizationRequest(
            customer_id="eval-zero",
            batches=[
                OptimizationBatch(batch_id="a", days_left=0, stock_qty=0, allowed_actions=[action]),
                OptimizationBatch(batch_id="b", days_left=1, stock_qty=0, allowed_actions=[action]),
            ],
            capacity_by_action={},
        ),
    ]
