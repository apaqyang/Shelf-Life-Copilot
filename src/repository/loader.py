"""JSON-backed repository: loaders for mock batches and customer configs."""

from __future__ import annotations

import json
from pathlib import Path

from src.models.batch import Batch
from src.models.customer import CustomerConfig

DEFAULT_DATA_ROOT = Path(__file__).resolve().parents[2] / "data"


def load_customer_config(
    customer_id: str,
    *,
    root: Path | None = None,
) -> CustomerConfig:
    """Load `<root>/config/<customer_id>.actions.json` into a CustomerConfig."""
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
    base = root if root is not None else DEFAULT_DATA_ROOT
    path = base / "batches" / f"{customer_id}.json"
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    return [Batch.model_validate(item) for item in payload]
