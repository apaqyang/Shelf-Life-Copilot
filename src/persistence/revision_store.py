"""Audited one-round revision sessions linking text feedback to suggestions."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

from src.persistence.sqlite import SQLiteDatabase


@dataclass(frozen=True)
class RevisionSession:
    session_id: int
    operator_id: str
    customer_id: str
    batch_id: str
    original_generated_at: datetime
    feedback: str | None
    status: str


class RevisionStore:
    def __init__(self, db_path: Path | str) -> None:
        self._db = SQLiteDatabase(db_path)

    def __enter__(self) -> RevisionStore:
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

    def open(
        self,
        *,
        operator_id: str,
        customer_id: str,
        batch_id: str,
        original_generated_at: datetime,
    ) -> RevisionSession:
        try:
            cursor = self._db.execute(
                """
                INSERT INTO revision_sessions (
                    operator_id, customer_id, batch_id, original_generated_at,
                    status, created_at
                ) VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (
                    operator_id,
                    customer_id,
                    batch_id,
                    original_generated_at.astimezone(UTC).isoformat(),
                    datetime.now(UTC).isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "a revision is already pending or this suggestion was revised"
            ) from exc
        assert cursor.lastrowid is not None  # noqa: S101
        return self._get(cursor.lastrowid)

    def attach_feedback(self, operator_id: str, feedback: str, event_id: str) -> RevisionSession:
        if not feedback.strip():
            raise ValueError("revision feedback must not be empty")
        row = self._db.fetchone(
            "SELECT id FROM revision_sessions WHERE operator_id = ? AND status = 'pending'",
            (operator_id,),
        )
        if row is None:
            raise KeyError("no pending revision for operator")
        session_id = int(str(row[0]))
        self._db.execute(
            """
            UPDATE revision_sessions SET feedback = ?, feedback_event_id = ?, status = 'processing'
            WHERE id = ?
            """,
            (feedback, event_id, session_id),
        )
        return self._get(session_id)

    def complete(self, session_id: int, revised_generated_at: datetime) -> None:
        self._db.execute(
            """
            UPDATE revision_sessions
            SET status = 'completed', revised_generated_at = ? WHERE id = ?
            """,
            (revised_generated_at.astimezone(UTC).isoformat(), session_id),
        )

    def fail(self, session_id: int) -> None:
        self._db.execute(
            "UPDATE revision_sessions SET status = 'failed' WHERE id = ?",
            (session_id,),
        )

    def _get(self, session_id: int) -> RevisionSession:
        row = self._db.fetchone(
            """
            SELECT id, operator_id, customer_id, batch_id, original_generated_at,
                   feedback, status FROM revision_sessions WHERE id = ?
            """,
            (session_id,),
        )
        if row is None:
            raise KeyError(session_id)
        return RevisionSession(
            session_id=int(str(row[0])),
            operator_id=str(row[1]),
            customer_id=str(row[2]),
            batch_id=str(row[3]),
            original_generated_at=datetime.fromisoformat(str(row[4])),
            feedback=None if row[5] is None else str(row[5]),
            status=str(row[6]),
        )
