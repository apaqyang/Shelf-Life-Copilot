from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import ValidationError

from src.models import ActionType, Batch, CustomerConfig
from src.repository import (
    ERPPage,
    JsonRepository,
    PagedERPRepository,
    PermanentERPError,
    RecoverableERPError,
    SAPBusinessOneClient,
)


def _payload(batch_id: str) -> dict[str, object]:
    return Batch(
        batch_id=batch_id,
        customer_id="c",
        material_id="m",
        material_name="food",
        production_date=date(2026, 1, 1),
        expiry_date=date(2026, 2, 1),
        stock_qty=1,
        unit="kg",
        warehouse="w",
    ).model_dump(mode="json")


def _config() -> CustomerConfig:
    return CustomerConfig(
        customer_id="c",
        industry="demo",
        enabled_actions=[ActionType.REPORT_LOSS],
        alert_thresholds={"yellow": 30, "orange": 15, "red": 7},
        decision_makers=[],
    )


def test_paginated_adapter_retries_and_delegates_config() -> None:
    client = MagicMock()
    client.fetch_batches.side_effect = [
        RecoverableERPError("timeout"),
        ERPPage([_payload("b1")], "next"),
        ERPPage([_payload("b2")]),
    ]
    configs = MagicMock()
    configs.load_customer_config.return_value = _config()
    sleeps: list[float] = []
    repo = PagedERPRepository(client, configs, max_retries=1, sleep=sleeps.append)
    assert [b.batch_id for b in repo.load_batches("c")] == ["b1", "b2"]
    assert sleeps == [0.1]
    assert repo.load_customer_config("c").customer_id == "c"
    assert client.fetch_batches.call_args_list[-1].kwargs["timeout_seconds"] == 10


@pytest.mark.parametrize(
    "kwargs", [{"timeout_seconds": 0}, {"max_retries": -1}, {"retry_delay_seconds": -1}]
)
def test_invalid_retry_configuration(kwargs: dict[str, float | int]) -> None:
    with pytest.raises(ValueError, match="invalid ERP"):
        PagedERPRepository(MagicMock(), MagicMock(), **kwargs)  # type: ignore[arg-type]


def test_duplicate_batches_and_cursor_loops_are_rejected() -> None:
    duplicate = MagicMock()
    duplicate.fetch_batches.return_value = ERPPage([_payload("b"), _payload("b")])
    with pytest.raises(ValueError, match="duplicate"):
        PagedERPRepository(duplicate, MagicMock()).load_batches("c")

    looping = MagicMock()
    looping.fetch_batches.side_effect = [ERPPage([], "same"), ERPPage([], "same")]
    with pytest.raises(PermanentERPError, match="cursor repeated"):
        PagedERPRepository(looping, MagicMock()).load_batches("c")


def test_retry_is_bounded() -> None:
    client = MagicMock()
    client.fetch_batches.side_effect = RecoverableERPError("still down")
    with pytest.raises(RecoverableERPError):
        PagedERPRepository(client, MagicMock(), max_retries=1, sleep=lambda _: None).load_batches(
            "c"
        )
    assert client.fetch_batches.call_count == 2


def test_json_and_erp_reject_duplicate_batch_ids(tmp_path: Path) -> None:
    (tmp_path / "batches").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "batches" / "c.json").write_text(
        json.dumps([_payload("same"), _payload("same")]), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="duplicate"):
        JsonRepository(tmp_path).load_batches("c")


def test_sap_business_one_maps_pages_and_rotates_credentials() -> None:
    requests: list[httpx.Request] = []
    tokens = iter(("B1SESSION=token-1; ROUTEID=.node1", "token-2"))

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        row = {
            "Batch": f"b{len(requests)}",
            "ItemCode": "item",
            "ItemDescription": "Frozen food",
            "ManufacturingDate": "2026-01-01T00:00:00Z",
            "ExpirationDate": "2026-02-01T00:00:00Z",
            "Quantity": 4,
            "UoM": "kg",
            "WarehouseCode": "w1",
        }
        body: dict[str, object] = {"value": [row]}
        if len(requests) == 1:
            body["@odata.nextLink"] = "/b1s/v2/SQLQueries('ShelfLifeBatches')/List?$skip=100"
        return httpx.Response(200, json=body)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = SAPBusinessOneClient(
        "https://sap.example", lambda: next(tokens), http_client=http, page_size=100
    )
    repository = PagedERPRepository(client, MagicMock())
    batches = repository.load_batches("tenant'o")
    assert [batch.batch_id for batch in batches] == ["b1", "b2"]
    assert requests[0].headers["cookie"] == "B1SESSION=token-1; ROUTEID=.node1"
    assert requests[1].headers["cookie"] == "B1SESSION=token-2"
    assert requests[0].url.params["customerId"] == "tenant'o"
    assert "b1s/v2/SQLQueries('ShelfLifeBatches')/List" in str(requests[0].url)
    assert requests[0].headers["prefer"] == "odata.maxpagesize=100"
    assert requests[1].url.params["$skip"] == "100"
    client.close()


@pytest.mark.parametrize(
    ("status", "error_type"),
    [(429, RecoverableERPError), (503, RecoverableERPError), (401, PermanentERPError)],
)
def test_sap_business_one_classifies_http_errors(status: int, error_type: type[Exception]) -> None:
    http = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(status, text="secret"))
    )
    client = SAPBusinessOneClient("https://sap.example", lambda: "credential", http_client=http)
    with pytest.raises(error_type, match="SAP"):
        client.fetch_batches("tenant", cursor=None, timeout_seconds=1)


def test_sap_business_one_rejects_transport_and_malformed_payloads() -> None:
    def failed(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("credential should not leak", request=request)

    transport_client = SAPBusinessOneClient(
        "https://sap.example",
        lambda: "credential",
        http_client=httpx.Client(transport=httpx.MockTransport(failed)),
    )
    with pytest.raises(RecoverableERPError, match="transport") as raised:
        transport_client.fetch_batches("tenant", cursor=None, timeout_seconds=1)
    assert "credential" not in str(raised.value)

    for payload in (
        {"value": ["bad"]},
        {"value": "not-a-list"},
        {"value": [], "@odata.nextLink": 42},
    ):
        malformed = SAPBusinessOneClient(
            "https://sap.example",
            lambda: "credential",
            http_client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda _request, body=payload: httpx.Response(200, json=body)
                )
            ),
        )
        with pytest.raises(PermanentERPError, match="invalid SAP"):
            malformed.fetch_batches("tenant", cursor=None, timeout_seconds=1)

    with pytest.raises(ValueError, match="invalid SAP"):
        SAPBusinessOneClient("ftp://sap.example", lambda: "credential")
    with pytest.raises(ValueError, match="invalid SAP"):
        SAPBusinessOneClient("https://sap.example", lambda: "credential", query_code="")


def _contract_repository(
    kind: str, tmp_path: Path, items: list[dict[str, object]]
) -> JsonRepository | PagedERPRepository:
    if kind == "json":
        (tmp_path / "batches").mkdir(exist_ok=True)
        (tmp_path / "config").mkdir(exist_ok=True)
        (tmp_path / "batches" / "c.json").write_text(json.dumps(items), encoding="utf-8")
        return JsonRepository(tmp_path)
    client = MagicMock()
    client.fetch_batches.return_value = ERPPage(items)
    return PagedERPRepository(client, MagicMock())


@pytest.mark.parametrize("kind", ["json", "erp"])
def test_batch_repository_shared_contract(kind: str, tmp_path: Path) -> None:
    assert _contract_repository(kind, tmp_path, []).load_batches("c") == []
    missing = _payload("missing")
    del missing["expiry_date"]
    with pytest.raises(ValidationError):
        _contract_repository(kind, tmp_path, [missing]).load_batches("c")
    negative = _payload("negative")
    negative["stock_qty"] = -1
    with pytest.raises(ValidationError):
        _contract_repository(kind, tmp_path, [negative]).load_batches("c")
    invalid_date = _payload("date")
    invalid_date["expiry_date"] = "not-a-date"
    with pytest.raises(ValidationError):
        _contract_repository(kind, tmp_path, [invalid_date]).load_batches("c")
    with pytest.raises(ValueError, match="duplicate"):
        _contract_repository(kind, tmp_path, [_payload("d"), _payload("d")]).load_batches("c")
