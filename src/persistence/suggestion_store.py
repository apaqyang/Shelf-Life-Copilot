"""SQLite store for LLM Suggestion entries.

Read by the webhook click handler so a 总监 ✅ 同意 click translates into a
Decision with the *real* action and savings_estimate (not TRANSFORM/0.0
placeholders). One row per LLM call; `latest_for_batch` returns the most
recent one keyed by (customer_id, batch_id).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from src.models import ActionType, Suggestion

_SCHEMA = """
CREATE TABLE IF NOT EXISTS suggestions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id          TEXT    NOT NULL,
    customer_id       TEXT    NOT NULL,
    action            TEXT    NOT NULL,
    savings_estimate  REAL    NOT NULL,
    rationale         TEXT    NOT NULL,
    confidence        REAL    NOT NULL,
    is_standard       INTEGER NOT NULL,
    llm_model         TEXT    NOT NULL,
    user_feedback     TEXT,
    generated_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_suggestions_lookup
    ON suggestions(customer_id, batch_id, generated_at DESC);
"""


class SuggestionStore:
    """Persist + look up the latest Suggestion per (customer_id, batch_id)."""

    def __init__(self, db_path: Path | str) -> None:
        # check_same_thread=False: FastAPI may dispatch requests on a worker
        # thread pool; v0.1 traffic is one write at a time so no concurrency risk.
        self._conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
        self._conn.executescript(_SCHEMA)

    def save(self, suggestion: Suggestion) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO suggestions (
                batch_id, customer_id, action, savings_estimate,
                rationale, confidence, is_standard, llm_model,
                user_feedback, generated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                suggestion.batch_id,
                suggestion.customer_id,
                suggestion.action.value,
                suggestion.savings_estimate,
                suggestion.rationale,
                suggestion.confidence,
                1 if suggestion.is_standard else 0,
                suggestion.llm_model,
                suggestion.user_feedback,
                suggestion.generated_at.isoformat(),
            ),
        )
        assert cur.lastrowid is not None  # noqa: S101  (sqlite INSERT contract)
        return cur.lastrowid

    def latest_for_batch(self, customer_id: str, batch_id: str) -> Suggestion | None:
        """Return the most-recently-generated suggestion for this batch, or None."""
        row = self._conn.execute(
            """
            SELECT batch_id, customer_id, action, savings_estimate,
                   rationale, confidence, is_standard, llm_model,
                   user_feedback, generated_at
            FROM suggestions
            WHERE customer_id = ? AND batch_id = ?
            ORDER BY generated_at DESC
            LIMIT 1
            """,
            (customer_id, batch_id),
        ).fetchone()

        if row is None:
            return None

        return Suggestion(
            batch_id=row[0],
            customer_id=row[1],
            action=ActionType(row[2]),
            savings_estimate=row[3],
            rationale=row[4],
            confidence=row[5],
            is_standard=bool(row[6]),
            llm_model=row[7],
            user_feedback=row[8],
            generated_at=datetime.fromisoformat(row[9]),
        )
