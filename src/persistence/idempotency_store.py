"""Persistent request idempotency records for callbacks and command APIs."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

from src.persistence.sqlite import SQLiteDatabase


@dataclass(frozen=True)
class IdempotencyRecord:
    idempotency_key: str
    request_kind: str
    status: str
    status_code: int | None
    response_json: str | None


class IdempotencyStore:
    """Claim, complete, and safely retry externally delivered requests."""

    def __init__(self, db_path: Path | str) -> None:
        self._db = SQLiteDatabase(db_path)

    @property
    def closed(self) -> bool:
        return self._db.closed

    def __enter__(self) -> IdempotencyStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    def claim(self, idempotency_key: str, request_kind: str) -> IdempotencyRecord | None:
        """Return None for a new claim, otherwise the previously stored record."""
        if not idempotency_key or not request_kind:
            raise ValueError("idempotency key and request kind must not be empty")
        try:
            self._db.execute(
                """
                INSERT INTO idempotency_records (
                    idempotency_key, request_kind, status, created_at
                ) VALUES (?, ?, 'processing', ?)
                """,
                (idempotency_key, request_kind, datetime.now(UTC).isoformat()),
            )
            return None
        except sqlite3.IntegrityError:
            row = self._db.fetchone(
                """
                SELECT idempotency_key, request_kind, status, status_code, response_json
                FROM idempotency_records WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            )
            assert row is not None  # noqa: S101 - unique conflict guarantees the row
            return IdempotencyRecord(
                idempotency_key=str(row[0]),
                request_kind=str(row[1]),
                status=str(row[2]),
                status_code=None if row[3] is None else int(str(row[3])),
                response_json=None if row[4] is None else str(row[4]),
            )

    def complete(self, idempotency_key: str, *, status_code: int, response_json: str) -> None:
        cur = self._db.execute(
            """
            UPDATE idempotency_records
            SET status = 'completed', status_code = ?, response_json = ?, completed_at = ?
            WHERE idempotency_key = ? AND status = 'processing'
            """,
            (status_code, response_json, datetime.now(UTC).isoformat(), idempotency_key),
        )
        if cur.rowcount != 1:
            raise KeyError(f"active idempotency claim {idempotency_key!r} not found")

    def release(self, idempotency_key: str) -> None:
        self._db.execute(
            "DELETE FROM idempotency_records WHERE idempotency_key = ? AND status = 'processing'",
            (idempotency_key,),
        )
