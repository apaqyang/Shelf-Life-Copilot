"""FastAPI router for /webhook/wecom (路径 B server-side).

v0.1 ships **plaintext mode** — no AES decryption, no signature check. This is
fine for self-testing in a controlled environment; production must wrap this
router with crypto middleware once corp_secret is available.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from src.persistence import DecisionStore
from src.webhook.handlers import (
    UnknownActionError,
    UnknownBatchError,
    handle_click,
)
from src.webhook.schemas import WecomCallbackResponse, WecomEvent

router = APIRouter()

_DEFAULT_DB = Path("data/decisions.db")


@lru_cache(maxsize=1)
def _default_store() -> DecisionStore:
    """Module-level singleton so all requests share one sqlite connection."""
    return DecisionStore(_DEFAULT_DB)


def get_decision_store() -> DecisionStore:
    """FastAPI dependency hook. Tests override via `app.dependency_overrides`."""
    return _default_store()


@router.get("/webhook/wecom", response_class=PlainTextResponse)
async def verify_url(echostr: Annotated[str, Query(...)]) -> str:
    """WeCom URL verification handshake.

    v0.1 echoes `echostr` verbatim — production must decrypt it with corp_secret
    before echoing (WeCom callback security spec). Without crypto this endpoint
    is only safe behind a private network / VPN, which matches v0.1 self-testing.
    """
    return echostr


@router.post("/webhook/wecom")
async def receive_event(
    event: WecomEvent,
    store: Annotated[DecisionStore, Depends(get_decision_store)],
) -> WecomCallbackResponse:
    """Route a WeCom callback event to the click handler, or 200 no-op."""
    if event.msg_type != "event" or event.event != "click":
        return WecomCallbackResponse(ok=True, detail="ignored (non-click message)")

    try:
        detail = handle_click(event, store)
    except UnknownActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnknownBatchError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return WecomCallbackResponse(ok=True, detail=detail)
