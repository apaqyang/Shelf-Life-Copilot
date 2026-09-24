"""FastAPI router for /webhook/wecom (路径 B server-side).

v0.1 ships **plaintext mode** — no AES decryption, no signature check. This is
fine for self-testing in a controlled environment; production must wrap this
router with crypto middleware once corp_secret is available.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from src.observability import log_event, metrics
from src.persistence import DecisionStore, IdempotencyStore, RevisionStore, SuggestionStore
from src.runtime.config import Settings
from src.scheduler import ScanRunner
from src.webhook.crypto import get_webhook_crypto
from src.webhook.handlers import (
    UnknownActionError,
    UnknownBatchError,
    handle_click,
)
from src.webhook.schemas import WecomCallbackResponse, WecomEvent

router = APIRouter()
logger = logging.getLogger(__name__)


def get_decision_store(request: Request) -> DecisionStore:
    """Return the lifespan-owned decision store."""
    return cast(DecisionStore, request.app.state.decision_store)


def get_suggestion_store(request: Request) -> SuggestionStore:
    """Return the lifespan-owned suggestion store."""
    return cast(SuggestionStore, request.app.state.suggestion_store)


def get_idempotency_store(request: Request) -> IdempotencyStore:
    return cast(IdempotencyStore, request.app.state.idempotency_store)


def get_runtime_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_revision_store(request: Request) -> RevisionStore:
    return cast(RevisionStore, request.app.state.revision_store)


def get_scan_runner(request: Request) -> ScanRunner:
    return cast(ScanRunner, request.app.state.scan_runner)


def _validate_event_timestamp(
    event: WecomEvent,
    replay_window_seconds: int,
    *,
    now: datetime | None = None,
) -> None:
    current = datetime.now(UTC) if now is None else now
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    age_seconds = abs(current.timestamp() - event.create_time)
    if age_seconds > replay_window_seconds:
        event_key = event.event_key or ""
        log_event(
            logger,
            logging.WARNING,
            "Rejected callback outside replay window",
            customer_id=event_key.split(":")[1] if event_key.count(":") == 2 else "unknown",
            correlation_id=event.stable_event_id,
            result="rejected",
            duration_ms=0,
            age_seconds=round(age_seconds),
        )
        raise HTTPException(status_code=400, detail="callback timestamp outside replay window")


@router.get("/webhook/wecom", response_class=PlainTextResponse)
async def verify_url(echostr: Annotated[str, Query(...)]) -> str:
    """WeCom URL verification handshake.

    Goes through the WebhookCrypto seam: v0.1 PlaintextCrypto echoes `echostr`
    verbatim, while the enterprise AES plugin decrypts it with corp_secret first
    (WeCom callback security spec). Without crypto this endpoint is only safe
    behind a private network / VPN, which matches v0.1 self-testing.
    """
    return get_webhook_crypto().verify_url(echostr)


@router.post("/webhook/wecom")
async def receive_event(
    event: WecomEvent,
    store: Annotated[DecisionStore, Depends(get_decision_store)],
    suggestion_store: Annotated[SuggestionStore, Depends(get_suggestion_store)],
    idempotency_store: Annotated[IdempotencyStore, Depends(get_idempotency_store)],
    settings: Annotated[Settings, Depends(get_runtime_settings)],
    revision_store: Annotated[RevisionStore, Depends(get_revision_store)],
    scan_runner: Annotated[ScanRunner, Depends(get_scan_runner)],
) -> WecomCallbackResponse:
    """Route a WeCom callback event to the click handler, or 200 no-op."""
    started = time.perf_counter()
    _validate_event_timestamp(event, settings.webhook_replay_window_seconds)
    event_id = event.stable_event_id
    previous = idempotency_store.claim(event_id, "wecom_callback")
    if previous is not None:
        metrics.increment("webhook_duplicate_total")
        if previous.status == "completed" and previous.response_json is not None:
            return WecomCallbackResponse.model_validate_json(previous.response_json)
        raise HTTPException(status_code=409, detail="callback is already being processed")

    try:
        if event.msg_type == "text":
            try:
                session = revision_store.attach_feedback(
                    event.from_user_name,
                    event.content or "",
                    event_id,
                )
            except KeyError:
                detail = "ignored (no pending revision)"
            else:
                try:
                    result = await scan_runner.revise_for_batch(
                        session.customer_id,
                        session.batch_id,
                        session.feedback or "",
                    )
                except Exception:
                    revision_store.fail(session.session_id)
                    raise
                if result.errors or not result.suggestions:
                    revision_store.fail(session.session_id)
                    raise HTTPException(status_code=502, detail="revision generation failed")
                revised = result.suggestions[0]
                revision_store.complete(session.session_id, revised.generated_at)
                detail = f"Revised suggestion recorded for {session.batch_id}"
        elif event.msg_type != "event" or event.event != "click":
            response = WecomCallbackResponse(ok=True, detail="ignored (non-click message)")
            idempotency_store.complete(
                event_id,
                status_code=200,
                response_json=response.model_dump_json(),
            )
            metrics.increment("webhook_processed_total")
            return response
        else:
            detail = handle_click(
                event,
                store,
                suggestion_store=suggestion_store,
                revision_store=revision_store,
            )
    except UnknownActionError as exc:
        idempotency_store.release(event_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnknownBatchError as exc:
        idempotency_store.release(event_id)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        idempotency_store.release(event_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        idempotency_store.release(event_id)
        raise

    response = WecomCallbackResponse(ok=True, detail=detail)
    idempotency_store.complete(
        event_id,
        status_code=200,
        response_json=response.model_dump_json(),
    )
    duration_ms = (time.perf_counter() - started) * 1000
    metrics.increment("webhook_processed_total")
    log_event(
        logger,
        logging.INFO,
        "webhook.completed",
        customer_id=(event.event_key or "unknown").split(":")[1]
        if (event.event_key or "").count(":") == 2
        else "unknown",
        correlation_id=event_id,
        result="success",
        duration_ms=duration_ms,
    )
    return response
