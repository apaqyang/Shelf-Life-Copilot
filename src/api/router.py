"""Authenticated, idempotent operational command endpoints."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from src.alerts import calculate_days_left
from src.api.schemas import (
    BatchListResponse,
    BatchScanStatus,
    CustomerListResponse,
    CustomerSummary,
    ManualScanRequest,
    ManualScanResponse,
    OptimizationPlanRequest,
    OptimizationPlanResponse,
    PageInfo,
    WorkOrderCompletionRequest,
    WorkOrderCompletionResponse,
    WorkOrderListResponse,
)
from src.models import WorkOrderReceipt
from src.optimization import (
    OptimizationBatch,
    OptimizationPlan,
    OptimizationRequest,
    priority_baseline,
)
from src.persistence import IdempotencyStore, OptimizationPlanStore, WorkOrderStore
from src.runtime.security import require_api_token
from src.runtime.tenant import Principal
from src.scheduler import ScanRunner

router = APIRouter(prefix="/api")


def _page(items: Sequence[object], cursor: int, limit: int) -> PageInfo:
    return PageInfo(next_cursor=cursor + limit if len(items) == limit else None)


@router.get("/customers", response_model=CustomerListResponse)
async def list_customers(
    request: Request,
    principal: Annotated[Principal, Depends(require_api_token)],
) -> CustomerListResponse:
    repository = request.app.state.batch_repository
    items = []
    for customer_id in sorted(principal.customer_ids):
        try:
            config = repository.load_customer_config(customer_id)
        except (FileNotFoundError, KeyError):
            continue
        items.append(CustomerSummary(customer_id=customer_id, industry=config.industry))
    return CustomerListResponse(items=items)


@router.get("/customers/{customer_id}/batches", response_model=BatchListResponse)
async def list_batches(
    customer_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_api_token)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[int, Query(ge=0)] = 0,
) -> BatchListResponse:
    principal.require_customer(customer_id)
    try:
        all_items = request.app.state.batch_repository.load_batches(customer_id)
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    items = all_items[cursor : cursor + limit]
    return BatchListResponse(items=items, page=_page(items, cursor, limit))


@router.get("/customers/{customer_id}/work-orders", response_model=WorkOrderListResponse)
async def list_work_orders(
    customer_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_api_token)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[int, Query(ge=0)] = 0,
) -> WorkOrderListResponse:
    principal.require_customer(customer_id)
    items = _work_order_store(request).list_for_customer(customer_id, limit=limit, offset=cursor)
    return WorkOrderListResponse(items=items, page=_page(items, cursor, limit))


def _idempotency_store(request: Request) -> IdempotencyStore:
    return cast(IdempotencyStore, request.app.state.idempotency_store)


def _scan_runner(request: Request) -> ScanRunner:
    return cast(ScanRunner, request.app.state.scan_runner)


def _work_order_store(request: Request) -> WorkOrderStore:
    return cast(WorkOrderStore, request.app.state.work_order_store)


def _optimization_store(request: Request) -> OptimizationPlanStore:
    return cast(OptimizationPlanStore, request.app.state.optimization_plan_store)


@router.post("/optimization-plans", response_model=OptimizationPlanResponse)
async def create_optimization_plan(
    command: OptimizationPlanRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_api_token)],
) -> OptimizationPlanResponse:
    principal.require_customer(command.customer_id)
    gate = request.app.state.optimization_gate
    if not gate.passed:
        raise HTTPException(status_code=503, detail="optimizer evaluation gate failed")
    repository = request.app.state.batch_repository
    try:
        batches = repository.load_batches(command.customer_id)
        config = repository.load_customer_config(command.customer_id)
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    today = command.today or date.today()
    candidates = [
        OptimizationBatch(
            batch_id=batch.batch_id,
            material_name=batch.material_name,
            days_left=calculate_days_left(batch.expiry_date, today),
            stock_qty=batch.stock_qty,
            allowed_actions=config.enabled_actions,
        )
        for batch in batches
    ]
    if len(candidates) < 2:
        raise HTTPException(status_code=409, detail="at least two batches are required")
    optimization_request = OptimizationRequest(
        customer_id=command.customer_id,
        batches=candidates,
        capacity_by_action=command.capacity_by_action,
    )
    result = priority_baseline(optimization_request)
    if not any(item.allocated_qty > 0 for item in result.assignments):
        raise HTTPException(status_code=409, detail="plan allocates no inventory")
    plan = OptimizationPlan(
        request=optimization_request,
        result=result,
    )
    _optimization_store(request).save(plan)
    return OptimizationPlanResponse(plan=plan, gate=gate)


@router.get("/optimization-plans/{plan_id}", response_model=OptimizationPlan)
async def get_optimization_plan(
    plan_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_api_token)],
) -> OptimizationPlan:
    plan = _optimization_store(request).get(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="optimization plan not found")
    principal.require_customer(plan.request.customer_id)
    return plan


@router.post("/optimization-plans/{plan_id}/execute", response_model=OptimizationPlan)
async def execute_optimization_plan(
    plan_id: str,
    request: Request,
    operator_id: Annotated[str, Header(alias="X-Operator-ID", min_length=1)],
    principal: Annotated[Principal, Depends(require_api_token)],
) -> OptimizationPlan:
    plan = _optimization_store(request).get(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="optimization plan not found")
    principal.require_customer(plan.request.customer_id)
    try:
        return _optimization_store(request).execute(
            plan_id, approved_by=operator_id, approved_at=datetime.now(UTC)
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _claim_or_replay(
    store: IdempotencyStore,
    key: str,
    kind: str,
    response_type: type[ManualScanResponse] | type[WorkOrderCompletionResponse],
) -> ManualScanResponse | WorkOrderCompletionResponse | None:
    previous = store.claim(key, kind)
    if previous is None:
        return None
    if previous.status == "completed" and previous.response_json is not None:
        return response_type.model_validate_json(previous.response_json)
    raise HTTPException(status_code=409, detail="request is already being processed")


@router.post("/scans", response_model=ManualScanResponse)
async def run_manual_scan(
    command: ManualScanRequest,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    principal: Annotated[Principal, Depends(require_api_token)],
) -> ManualScanResponse:
    principal.require_customer(command.customer_id)
    store = _idempotency_store(request)
    key = f"manual_scan:{idempotency_key}"
    replay = _claim_or_replay(store, key, "manual_scan", ManualScanResponse)
    if replay is not None:
        assert isinstance(replay, ManualScanResponse)  # noqa: S101 - narrowed by response type
        return replay
    try:
        result = await _scan_runner(request).run_for_customer(
            command.customer_id,
            today=command.today,
            skip_llm=command.skip_llm,
        )
    except ValueError as exc:
        store.release(key)
        if "engine is required" in str(exc):
            raise HTTPException(status_code=503, detail="LLM provider is unavailable") from exc
        raise
    except (FileNotFoundError, KeyError) as exc:
        store.release(key)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        store.release(key)
        raise

    errors = {error.batch_id: error.message for error in result.errors}
    batch_ids = result.batch_ids or [alert.batch_id for alert in result.alerts]
    response = ManualScanResponse(
        customer_id=result.customer_id,
        total_batches=result.total_batches,
        alert_count=len(result.alerts),
        suggestion_count=len(result.suggestions),
        card_count=len(result.cards),
        batch_results=[
            BatchScanStatus(
                batch_id=batch_id,
                status="failed" if batch_id in errors else "succeeded",
                detail=errors.get(batch_id),
            )
            for batch_id in batch_ids
        ],
    )
    store.complete(key, status_code=200, response_json=response.model_dump_json())
    return response


@router.post(
    "/work-orders/{work_order_id}/complete",
    response_model=WorkOrderCompletionResponse,
)
async def complete_work_order(
    work_order_id: str,
    command: WorkOrderCompletionRequest,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    operator_id: Annotated[str, Header(alias="X-Operator-ID", min_length=1)],
    principal: Annotated[Principal, Depends(require_api_token)],
) -> WorkOrderCompletionResponse:
    existing = _work_order_store(request).get(work_order_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"work order {work_order_id!r} not found")
    principal.require_customer(existing.customer_id)
    idempotency = _idempotency_store(request)
    key = f"work_order_completion:{idempotency_key}"
    replay = _claim_or_replay(
        idempotency,
        key,
        "work_order_completion",
        WorkOrderCompletionResponse,
    )
    if replay is not None:
        assert isinstance(replay, WorkOrderCompletionResponse)  # noqa: S101
        return replay
    try:
        order = _work_order_store(request).complete(
            work_order_id,
            WorkOrderReceipt(
                actual_qty=command.actual_qty,
                actual_savings=command.actual_savings,
                completed_by=operator_id,
                completed_at=datetime.now(UTC),
                source=command.source,
            ),
        )
    except KeyError as exc:
        idempotency.release(key)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        idempotency.release(key)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        idempotency.release(key)
        raise
    response = WorkOrderCompletionResponse(work_order=order)
    idempotency.complete(key, status_code=200, response_json=response.model_dump_json())
    return response
