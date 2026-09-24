"""SQLite adapter for LLM suggestion entries."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import cast

from src.models import ActionType, Suggestion
from src.persistence.sqlite import SQLiteDatabase


class SuggestionStore:
    """Persist and look up the latest suggestion for a customer batch."""

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

    def __enter__(self) -> SuggestionStore:
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

    def save(self, suggestion: Suggestion) -> int:
        cur = self._db.execute(
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
                int(suggestion.is_standard),
                suggestion.llm_model,
                suggestion.user_feedback,
                suggestion.generated_at.astimezone(UTC).isoformat(),
            ),
        )
        assert cur.lastrowid is not None  # noqa: S101 - sqlite INSERT contract
        return cur.lastrowid

    def latest_for_batch(self, customer_id: str, batch_id: str) -> Suggestion | None:
        row = self._db.fetchone(
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
        )
        if row is None:
            return None
        return Suggestion(
            batch_id=str(row[0]),
            customer_id=str(row[1]),
            action=ActionType(str(row[2])),
            savings_estimate=cast(float, row[3]),
            rationale=str(row[4]),
            confidence=cast(float, row[5]),
            is_standard=bool(row[6]),
            llm_model=str(row[7]),
            user_feedback=None if row[8] is None else str(row[8]),
            generated_at=datetime.fromisoformat(str(row[9])),
        )
