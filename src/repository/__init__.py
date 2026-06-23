"""JSON-backed repository for v0.1 mock data + the BatchRepository seam."""

from src.repository.loader import DEFAULT_DATA_ROOT, load_batches, load_customer_config
from src.repository.protocol import (
    BatchRepository,
    JsonRepository,
    get_repository,
    reset_repository,
    set_repository,
)

__all__ = [
    "DEFAULT_DATA_ROOT",
    "BatchRepository",
    "JsonRepository",
    "get_repository",
    "load_batches",
    "load_customer_config",
    "reset_repository",
    "set_repository",
]
