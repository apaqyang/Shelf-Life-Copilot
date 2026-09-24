"""ERP pagination/retry contract and BatchRepository adapter."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from src.models import Batch, CustomerConfig
from src.repository.protocol import BatchRepository


class ERPError(Exception):
    """Base ERP integration failure."""


class RecoverableERPError(ERPError):
    """Timeout, throttling, or transient server failure eligible for retry."""


class PermanentERPError(ERPError):
    """Authentication, authorization, or invalid-request failure."""


@dataclass(frozen=True)
class ERPPage:
    items: list[dict[str, Any]]
    next_cursor: str | None = None


class ERPClient(Protocol):
    def fetch_batches(
        self, customer_id: str, *, cursor: str | None, timeout_seconds: float
    ) -> ERPPage: ...  # pragma: no cover


class PagedERPRepository:
    """Normalize a paginated ERP client into the core repository contract."""

    def __init__(
        self,
        client: ERPClient,
        config_repository: BatchRepository,
        *,
        timeout_seconds: float = 10,
        max_retries: int = 2,
        retry_delay_seconds: float = 0.1,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout_seconds <= 0 or max_retries < 0 or retry_delay_seconds < 0:
            raise ValueError("invalid ERP timeout/retry configuration")
        self._client = client
        self._config_repository = config_repository
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds
        self._sleep = sleep

    def load_customer_config(self, customer_id: str) -> CustomerConfig:
        return self._config_repository.load_customer_config(customer_id)

    def load_batches(self, customer_id: str) -> list[Batch]:
        cursor: str | None = None
        batches: list[Batch] = []
        seen_cursors: set[str] = set()
        while True:
            page = self._fetch_with_retry(customer_id, cursor)
            batches.extend(Batch.model_validate(item) for item in page.items)
            if page.next_cursor is None:
                break
            if page.next_cursor in seen_cursors:
                raise PermanentERPError("ERP pagination cursor repeated")
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor
        ids = [batch.batch_id for batch in batches]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate batch_id in customer {customer_id!r}")
        return batches

    def _fetch_with_retry(self, customer_id: str, cursor: str | None) -> ERPPage:
        for attempt in range(self._max_retries + 1):
            try:
                return self._client.fetch_batches(
                    customer_id,
                    cursor=cursor,
                    timeout_seconds=self._timeout_seconds,
                )
            except RecoverableERPError:
                if attempt == self._max_retries:
                    raise
                self._sleep(self._retry_delay_seconds * (2**attempt))
        raise AssertionError("unreachable")  # pragma: no cover
