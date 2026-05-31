"""WecomClient Protocol + DryRunWecomClient + WebhookWecomClient.

Two transports ship in v0.1:
- DryRunWecomClient: in-memory, no network, default for tests and demos
- WebhookWecomClient: group-bot webhook (no admin permission needed; one URL)

Application-message + interactive callbacks land in v0.5 once a customer
approves admin-level API access.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

import httpx

from src.models import Card

logger = logging.getLogger(__name__)


@runtime_checkable
class WecomClient(Protocol):
    """Sends a rendered Card to WeCom. Async to match future HTTP impl."""

    async def send_card(self, card: Card) -> None: ...  # pragma: no cover


class DryRunWecomClient:
    """In-memory WeCom client. Records every card for inspection in tests / demos."""

    def __init__(self) -> None:
        self.sent: list[Card] = []

    async def send_card(self, card: Card) -> None:
        self.sent.append(card)
        logger.info(
            "[DryRun] send_card kind=%s batch=%s title=%s",
            card.kind.value,
            card.batch_id,
            card.title,
        )


class WecomPushError(Exception):
    """Raised when the WeCom webhook returns non-zero errcode or the HTTP call fails."""


class WebhookWecomClient:
    """Push cards via the WeCom *group bot* webhook (no admin permission required).

    Why this over the application-message API:
    - One URL, no corp_id / agent_id / secret juggling
    - Any group owner can mint a webhook from the WeChat Work client
    - Sufficient for v0.1 demos where buttons are presenter-narrated, not clicked

    Limitations (documented, on purpose):
    - Markdown only; no interactive button callbacks (use AppMessageWecomClient in v0.5)
    - 4096-byte content limit per WeCom docs (we don't truncate; let it error and learn)
    """

    _DEFAULT_TIMEOUT_S = 10.0

    def __init__(
        self,
        webhook_url: str,
        *,
        timeout: float = _DEFAULT_TIMEOUT_S,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = webhook_url
        self._timeout = timeout
        # Caller-injected client wins (lets tests use MockTransport, lets long-running
        # processes reuse one connection pool). Otherwise we spin up a per-call client
        # so the constructor stays sync and side-effect-free.
        self._http = http_client

    async def send_card(self, card: Card) -> None:
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": card.markdown},
        }

        if self._http is not None:
            await self._post(self._http, payload, card)
            return

        async with httpx.AsyncClient(timeout=self._timeout) as http:
            await self._post(http, payload, card)

    async def _post(self, http: httpx.AsyncClient, payload: Mapping[str, Any], card: Card) -> None:
        try:
            resp = await http.post(self._url, json=payload, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise WecomPushError(f"HTTP transport failed: {exc}") from exc

        if resp.status_code >= 400:
            raise WecomPushError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        try:
            body = resp.json()
        except ValueError as exc:
            raise WecomPushError(f"non-JSON response: {resp.text[:200]}") from exc

        errcode = body.get("errcode")
        if errcode != 0:
            raise WecomPushError(f"wecom errcode={errcode} errmsg={body.get('errmsg')!r}")

        logger.info(
            "[Webhook] send_card kind=%s batch=%s title=%s",
            card.kind.value,
            card.batch_id,
            card.title,
        )
