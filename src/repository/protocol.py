"""Data-source seam — the Open Core boundary for swapping mock JSON with ERP.

v0.1 reads batches + customer config from local JSON (`JsonRepository`). The
enterprise ERP plugins (SAP / 用友 / 金蝶) implement this same `BatchRepository`
protocol and register themselves via `set_repository`, so everything downstream
(ScanRunner, webhook handlers, CLI) never learns where the data came from.

Keeping this seam in the open-source core — but shipping only the JSON impl —
is what lets a paid ERP adapter slot in without forking the core.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from src.models.batch import Batch
from src.models.customer import CustomerConfig
from src.repository.loader import DEFAULT_DATA_ROOT, load_batches, load_customer_config


@runtime_checkable
class BatchRepository(Protocol):
    """Where batches + customer configs come from. JSON now, ERP later."""

    def load_batches(self, customer_id: str) -> list[Batch]: ...  # pragma: no cover

    def load_customer_config(self, customer_id: str) -> CustomerConfig: ...  # pragma: no cover


class JsonRepository:
    """Default repository — the v0.1 mock JSON loaders behind the protocol."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root if root is not None else DEFAULT_DATA_ROOT

    def load_batches(self, customer_id: str) -> list[Batch]:
        return load_batches(customer_id, root=self._root)

    def load_customer_config(self, customer_id: str) -> CustomerConfig:
        return load_customer_config(customer_id, root=self._root)


_active_repository: BatchRepository | None = None


def get_repository() -> BatchRepository:
    """Return the active repository — JsonRepository unless a plugin overrode it."""
    global _active_repository
    if _active_repository is None:
        _active_repository = JsonRepository()
    return _active_repository


def set_repository(repo: BatchRepository) -> None:
    """Install a repository implementation (enterprise ERP plugins call this)."""
    global _active_repository
    _active_repository = repo


def reset_repository() -> None:
    """Drop back to the default JSON repository — primarily for tests."""
    global _active_repository
    _active_repository = None
