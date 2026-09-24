from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.persistence import RevisionStore


def test_revision_session_lifecycle_and_one_round_rule() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    with RevisionStore(":memory:") as store:
        opened = store.open(
            operator_id="worker",
            customer_id="c",
            batch_id="b",
            original_generated_at=timestamp,
        )
        assert opened.status == "pending"
        with pytest.raises(ValueError, match="already pending"):
            store.open(
                operator_id="worker",
                customer_id="c2",
                batch_id="b2",
                original_generated_at=timestamp,
            )
        attached = store.attach_feedback("worker", "change it", "event-1")
        assert attached.feedback == "change it"
        store.complete(attached.session_id, timestamp)
        with pytest.raises(ValueError, match="was revised"):
            store.open(
                operator_id="other",
                customer_id="c",
                batch_id="b",
                original_generated_at=timestamp,
            )


def test_revision_failures_are_audited() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    store = RevisionStore(":memory:")
    with pytest.raises(KeyError, match="no pending"):
        store.attach_feedback("nobody", "text", "event")
    store.open(
        operator_id="worker",
        customer_id="c",
        batch_id="b",
        original_generated_at=timestamp,
    )
    with pytest.raises(ValueError, match="must not be empty"):
        store.attach_feedback("worker", " ", "event")
    session = store.attach_feedback("worker", "try", "event")
    store.fail(session.session_id)
    with pytest.raises(KeyError):
        store._get(999)  # noqa: SLF001
    store.close()
