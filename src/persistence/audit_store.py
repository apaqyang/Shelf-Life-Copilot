"""Append-only security audit archive backed by SQLite."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from src.persistence.sqlite import SQLiteDatabase


class SecurityAuditEvent(BaseModel):
    """A security event safe for durable storage and administrator queries."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    occurred_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    event_type: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    path: str = Field(min_length=1)
    customer_id: str | None = None
    trace_id: str | None = None


def validate_audit_query(
    start: datetime,
    end: datetime,
    *,
    limit: int,
    offset: int,
) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("audit period boundaries must be timezone-aware")
    if start >= end:
        raise ValueError("audit period must be ordered")
    if limit <= 0 or offset < 0:
        raise ValueError("audit pagination is invalid")


class SecurityAuditStore:
    """Persist immutable audit events; only retention cleanup can remove them."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        self._db = SQLiteDatabase(db_path, busy_timeout_ms=busy_timeout_ms)

    @property
    def closed(self) -> bool:
        return self._db.closed

    @property
    def schema_version(self) -> int:
        return self._db.schema_version

    def __enter__(self) -> SecurityAuditStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def record(self, event: SecurityAuditEvent) -> None:
        self._db.execute(
            """INSERT INTO security_audit_events (
                   event_id, occurred_at, event_type, subject, reason, path,
                   customer_id, trace_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.event_id,
                event.occurred_at.astimezone(UTC).isoformat(),
                event.event_type,
                event.subject,
                event.reason,
                event.path,
                event.customer_id,
                event.trace_id,
            ),
        )

    def list_for_period(
        self,
        customer_id: str,
        start: datetime,
        end: datetime,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SecurityAuditEvent]:
        validate_audit_query(start, end, limit=limit, offset=offset)
        rows = self._db.fetchall(
            """SELECT event_id, occurred_at, event_type, subject, reason, path,
                      customer_id, trace_id
               FROM security_audit_events
               WHERE customer_id = ? AND occurred_at >= ? AND occurred_at < ?
               ORDER BY occurred_at DESC, event_id ASC
               LIMIT ? OFFSET ?""",
            (
                customer_id,
                start.astimezone(UTC).isoformat(),
                end.astimezone(UTC).isoformat(),
                limit,
                offset,
            ),
        )
        return [_event_from_row(row) for row in rows]

    def purge_before(self, cutoff: datetime) -> int:
        if cutoff.tzinfo is None:
            raise ValueError("audit retention cutoff must be timezone-aware")
        cursor = self._db.execute(
            "DELETE FROM security_audit_events WHERE occurred_at < ?",
            (cutoff.astimezone(UTC).isoformat(),),
        )
        return cursor.rowcount

    def close(self) -> None:
        self._db.close()


def _event_from_row(row: tuple[object, ...]) -> SecurityAuditEvent:
    return SecurityAuditEvent(
        event_id=str(row[0]),
        occurred_at=datetime.fromisoformat(str(row[1])),
        event_type=str(row[2]),
        subject=str(row[3]),
        reason=str(row[4]),
        path=str(row[5]),
        customer_id=None if row[6] is None else str(row[6]),
        trace_id=None if row[7] is None else str(row[7]),
    )
