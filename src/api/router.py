"""Authenticated, idempotent operational command endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from src.api.schemas import (
    BatchScanStatus,
    ManualScanRequest,
    ManualScanResponse,
    WorkOrderCompletionRequest,
    WorkOrderCompletionResponse,
)
from src.models import WorkOrderReceipt
from src.persistence import IdempotencyStore, WorkOrderStore
from src.runtime.security import require_api_token
from src.scheduler import ScanRunner

router = APIRouter(prefix="/api", dependencies=[Depends(require_api_token)])


def _idempotency_store(request: Request) -> IdempotencyStore:
    return cast(IdempotencyStore, request.app.state.idempotency_store)


def _scan_runner(request: Request) -> ScanRunner:
    return cast(ScanRunner, request.app.state.scan_runner)


def _work_order_store(request: Request) -> WorkOrderStore:
    return cast(WorkOrderStore, request.app.state.work_order_store)


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
) -> ManualScanResponse:
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
) -> WorkOrderCompletionResponse:
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
