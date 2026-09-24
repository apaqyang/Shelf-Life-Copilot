"""Request and response contracts for authenticated operational commands."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat

from src.models import ActionType, Batch, WorkOrder
from src.optimization import OptimizationGate, OptimizationPlan


class PageInfo(BaseModel):
    next_cursor: int | None = None


class CustomerSummary(BaseModel):
    customer_id: str
    industry: str


class CustomerListResponse(BaseModel):
    items: list[CustomerSummary]


class BatchListResponse(BaseModel):
    items: list[Batch]
    page: PageInfo


class WorkOrderListResponse(BaseModel):
    items: list[WorkOrder]
    page: PageInfo


class OptimizationPlanRequest(BaseModel):
    customer_id: str = Field(min_length=1)
    capacity_by_action: dict[ActionType, NonNegativeFloat]
    today: date | None = None


class OptimizationPlanResponse(BaseModel):
    plan: OptimizationPlan
    gate: OptimizationGate


class ManualScanRequest(BaseModel):
    customer_id: str = Field(min_length=1)
    today: date | None = None
    skip_llm: bool = False


class BatchScanStatus(BaseModel):
    batch_id: str
    status: str
    detail: str | None = None


class ManualScanResponse(BaseModel):
    customer_id: str
    total_batches: int
    alert_count: int
    suggestion_count: int
    card_count: int
    batch_results: list[BatchScanStatus]


class WorkOrderCompletionRequest(BaseModel):
    actual_qty: NonNegativeFloat
    actual_savings: NonNegativeFloat
    source: str = Field(min_length=1)


class WorkOrderCompletionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    work_order: WorkOrder
