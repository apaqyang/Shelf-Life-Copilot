"""FastAPI router for /webhook/wecom (路径 B server-side).

v0.1 ships **plaintext mode** — no AES decryption, no signature check. This is
fine for self-testing in a controlled environment; production must wrap this
router with crypto middleware once corp_secret is available.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from src.persistence import DecisionStore, IdempotencyStore, SuggestionStore
from src.runtime.config import Settings
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
        logger.warning(
            "Rejected callback outside replay window: event_id=%s age_seconds=%.0f",
            event.stable_event_id,
            age_seconds,
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
) -> WecomCallbackResponse:
    """Route a WeCom callback event to the click handler, or 200 no-op."""
    _validate_event_timestamp(event, settings.webhook_replay_window_seconds)
    event_id = event.stable_event_id
    previous = idempotency_store.claim(event_id, "wecom_callback")
    if previous is not None:
        if previous.status == "completed" and previous.response_json is not None:
            return WecomCallbackResponse.model_validate_json(previous.response_json)
        raise HTTPException(status_code=409, detail="callback is already being processed")

    try:
        if event.msg_type != "event" or event.event != "click":
            response = WecomCallbackResponse(ok=True, detail="ignored (non-click message)")
            idempotency_store.complete(
                event_id,
                status_code=200,
                response_json=response.model_dump_json(),
            )
            return response
        detail = handle_click(event, store, suggestion_store=suggestion_store)
    except UnknownActionError as exc:
        idempotency_store.release(event_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnknownBatchError as exc:
        idempotency_store.release(event_id)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        idempotency_store.release(event_id)
        raise

    response = WecomCallbackResponse(ok=True, detail=detail)
    idempotency_store.complete(
        event_id,
        status_code=200,
        response_json=response.model_dump_json(),
    )
    return response
