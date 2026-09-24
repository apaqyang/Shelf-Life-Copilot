from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from src.models import ActionType, Batch, CustomerConfig
from src.repository import (
    ERPPage,
    JsonRepository,
    PagedERPRepository,
    PermanentERPError,
    RecoverableERPError,
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
