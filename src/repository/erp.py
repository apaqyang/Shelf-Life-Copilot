"""ERP pagination/retry contract and BatchRepository adapter."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

import httpx

from src.models import Batch, CustomerConfig
from src.observability import trace_headers
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


class SAPBusinessOneClient:
    """SAP Business One Service Layer adapter backed by a reviewed SQLQuery."""

    def __init__(
        self,
        base_url: str,
        session_cookie_provider: Callable[[], str],
        *,
        query_code: str = "ShelfLifeBatches",
        page_size: int = 100,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not base_url.startswith(("https://", "http://")) or not query_code or page_size <= 0:
            raise ValueError("invalid SAP Service Layer configuration")
        self._base_url = base_url.rstrip("/")
        self._session_cookie_provider = session_cookie_provider
        self._query_code = query_code
        self._page_size = page_size
        self._http = http_client or httpx.Client()

    def fetch_batches(
        self, customer_id: str, *, cursor: str | None, timeout_seconds: float
    ) -> ERPPage:
        query_code = _odata_literal(self._query_code)
        url = cursor or f"{self._base_url}/b1s/v2/SQLQueries('{query_code}')/List"
        if cursor is not None and not cursor.startswith(("https://", "http://")):
            url = f"{self._base_url}/{cursor.lstrip('/')}"
        params: dict[str, str | int] | None = None
        if cursor is None:
            params = {
                "customerId": customer_id,
            }
        cookie = self._session_cookie_provider()
        if not cookie.startswith("B1SESSION="):
            cookie = f"B1SESSION={cookie}"
        try:
            response = self._http.get(
                url,
                params=params,
                headers={
                    "Cookie": cookie,
                    "Accept": "application/json",
                    "Prefer": f"odata.maxpagesize={self._page_size}",
                    **trace_headers(),
                },
                timeout=timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise RecoverableERPError("SAP transport failure") from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise RecoverableERPError(f"SAP transient HTTP {response.status_code}")
        if response.status_code >= 400:
            raise PermanentERPError(f"SAP rejected request with HTTP {response.status_code}")
        try:
            body = response.json()
            rows = body["value"]
            if not isinstance(rows, list):
                raise TypeError
            items = [_sap_batch(row, customer_id) for row in rows]
            next_cursor = body.get("@odata.nextLink")
            if next_cursor is not None and not isinstance(next_cursor, str):
                raise TypeError
        except (KeyError, TypeError, ValueError) as exc:
            raise PermanentERPError("invalid SAP batch response") from exc
        return ERPPage(items=items, next_cursor=next_cursor)

    def close(self) -> None:
        self._http.close()


def _odata_literal(value: str) -> str:
    return value.replace("'", "''")


def _sap_batch(row: object, customer_id: str) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise TypeError
    production_date = date.fromisoformat(str(row["ManufacturingDate"])[:10])
    expiry_date = date.fromisoformat(str(row["ExpirationDate"])[:10])
    return Batch(
        batch_id=str(row["Batch"]),
        customer_id=customer_id,
        material_id=str(row["ItemCode"]),
        material_name=str(row["ItemDescription"]),
        production_date=production_date,
        expiry_date=expiry_date,
        stock_qty=float(row["Quantity"]),
        unit=str(row["UoM"]),
        warehouse=str(row["WarehouseCode"]),
    ).model_dump(mode="json")


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
