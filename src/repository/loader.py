"""JSON-backed repository: loaders for mock batches and customer configs."""

from __future__ import annotations

import json
from pathlib import Path

from src.models.batch import Batch
from src.models.customer import CustomerConfig

DEFAULT_DATA_ROOT = Path(__file__).resolve().parents[2] / "data"


def _validate_customer_id(customer_id: str) -> None:
    if not customer_id or customer_id in {".", ".."} or "/" in customer_id or "\\" in customer_id:
        raise ValueError("customer_id must be a non-empty file-name component")


def load_customer_config(
    customer_id: str,
    *,
    root: Path | None = None,
) -> CustomerConfig:
    """Load `<root>/config/<customer_id>.actions.json` into a CustomerConfig."""
    _validate_customer_id(customer_id)
    base = root if root is not None else DEFAULT_DATA_ROOT
    path = base / "config" / f"{customer_id}.actions.json"
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    return CustomerConfig.model_validate(payload)


def load_batches(
    customer_id: str,
    *,
    root: Path | None = None,
) -> list[Batch]:
    """Load `<root>/batches/<customer_id>.json` into a list of Batch objects."""
    _validate_customer_id(customer_id)
    base = root if root is not None else DEFAULT_DATA_ROOT
    path = base / "batches" / f"{customer_id}.json"
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    batches = [Batch.model_validate(item) for item in payload]
    batch_ids = [batch.batch_id for batch in batches]
    if len(batch_ids) != len(set(batch_ids)):
        raise ValueError(f"duplicate batch_id in customer {customer_id!r}")
    return batches
