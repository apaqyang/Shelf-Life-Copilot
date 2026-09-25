"""Persistent idempotency claim lifecycle."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from src.persistence import IdempotencyStore


def test_claim_complete_and_replay_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "idempotency.db"
    with IdempotencyStore(path) as store:
        assert store.claim("key-1", "scan") is None
        processing = store.claim("key-1", "scan")
        assert processing is not None
        assert processing.status == "processing"
        store.complete("key-1", status_code=200, response_json='{"ok":true}')
    assert store.closed
    with IdempotencyStore(path) as reopened:
        completed = reopened.claim("key-1", "scan")
        assert completed is not None
        assert completed.status == "completed"
        assert completed.status_code == 200
        assert completed.response_json == '{"ok":true}'


def test_release_allows_retry() -> None:
    with IdempotencyStore(":memory:") as store:
        store.claim("key-1", "scan")
        store.release("key-1")
        assert store.claim("key-1", "scan") is None


def test_invalid_claim_or_missing_completion_is_rejected() -> None:
    with IdempotencyStore(":memory:") as store:
        with pytest.raises(ValueError, match="must not be empty"):
            store.claim("", "scan")
        with pytest.raises(ValueError, match="must not be empty"):
            store.claim("key", "")
        with pytest.raises(KeyError, match="not found"):
            store.complete("missing", status_code=200, response_json="{}")


def test_concurrent_instances_claim_shared_request_only_once(tmp_path: Path) -> None:
    path = tmp_path / "shared-idempotency.db"
    with IdempotencyStore(path):
        pass
    barrier = Barrier(2)

    def claim() -> bool:
        with IdempotencyStore(path) as store:
            barrier.wait()
            return store.claim("same-request", "scan") is None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: claim(), range(2)))

    assert sorted(results) == [False, True]
