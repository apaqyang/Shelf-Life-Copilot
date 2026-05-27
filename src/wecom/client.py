"""WecomClient Protocol + DryRunWecomClient.

v0.1 only ships the dry-run client — it collects Card payloads in memory and
logs them so demos work without WeCom admin permission. The real
`HttpWecomClient` will land in v0.5 once the customer approves API access.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

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
