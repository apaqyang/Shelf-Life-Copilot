from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.persistence import LATEST_SCHEMA_VERSION, SecurityAuditEvent, SecurityAuditStore


def _event(
    event_id: str,
    occurred_at: datetime,
    *,
    customer_id: str | None = "customerA",
) -> SecurityAuditEvent:
    return SecurityAuditEvent(
        event_id=event_id,
        occurred_at=occurred_at,
        event_type="authorization.denied",
        subject="user-1",
        reason="customer",
        path="/api/customers/customerB/batches",
        customer_id=customer_id,
        trace_id="00-a-b-01",
    )


def test_security_audit_archive_roundtrip_paging_and_retention(tmp_path: Path) -> None:
    path = tmp_path / "audit.db"
    start = datetime(2026, 1, 1, tzinfo=UTC)
    middle = datetime(2026, 2, 1, tzinfo=UTC)
    end = datetime(2026, 3, 1, tzinfo=UTC)
    with SecurityAuditStore(path) as store:
        assert store.closed is False
        assert store.schema_version == LATEST_SCHEMA_VERSION
        store.record(_event("old", start))
        store.record(_event("new", middle))
        store.record(_event("other", middle, customer_id="customerB"))
        store.record(_event("global", middle, customer_id=None))
        assert store.list_for_period("customerA", start, end, limit=1, offset=0) == [
            _event("new", middle)
        ]
        assert store.list_for_period("customerA", start, end, limit=1, offset=1) == [
            _event("old", start)
        ]
        assert store.purge_before(middle) == 1
        assert store.list_for_period("customerA", start, end) == [_event("new", middle)]
    assert store.closed is True

    reopened = SecurityAuditStore(path)
    assert reopened.list_for_period("customerA", start, end) == [_event("new", middle)]
    reopened.close()


@pytest.mark.parametrize(
    ("start", "end", "limit", "offset", "message"),
    [
        (datetime(2026, 1, 1), datetime(2026, 2, 1, tzinfo=UTC), 1, 0, "timezone-aware"),
        (
            datetime(2026, 2, 1, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC),
            1,
            0,
            "ordered",
        ),
        (
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 2, 1, tzinfo=UTC),
            0,
            0,
            "pagination",
        ),
        (
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 2, 1, tzinfo=UTC),
            1,
            -1,
            "pagination",
        ),
    ],
)
def test_security_audit_query_validation(
    tmp_path: Path,
    start: datetime,
    end: datetime,
    limit: int,
    offset: int,
    message: str,
) -> None:
    store = SecurityAuditStore(tmp_path / "invalid.db")
    with pytest.raises(ValueError, match=message):
        store.list_for_period("customerA", start, end, limit=limit, offset=offset)
    store.close()


def test_security_audit_retention_requires_aware_cutoff(tmp_path: Path) -> None:
    store = SecurityAuditStore(tmp_path / "retention.db")
    with pytest.raises(ValueError, match="timezone-aware"):
        store.purge_before(datetime(2026, 1, 1))
    store.close()
