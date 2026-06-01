"""SQLite store for Decision log entries.

One table, no ORM. We persist the tz-aware `decided_at` as ISO 8601 text so
sorting works lexicographically and we can read it back without dateutil.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from src.models import ActionType, Decision, DecisionOutcome

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id          TEXT    NOT NULL,
    customer_id       TEXT    NOT NULL,
    material_name     TEXT    NOT NULL,
    decided_at        TEXT    NOT NULL,
    action            TEXT    NOT NULL,
    outcome           TEXT    NOT NULL,
    savings_estimate  REAL    NOT NULL,
    actual_savings    REAL,
    actual_qty        REAL,
    notes             TEXT
);
CREATE INDEX IF NOT EXISTS idx_decisions_customer_period
    ON decisions(customer_id, decided_at);
"""


def _require_tz(name: str, value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")


class DecisionStore:
    """Persist and query Decision entries by customer + time window.

    Uses one long-lived sqlite3.Connection so `:memory:` databases survive
    across calls within the same instance (tests rely on this). For file-backed
    paths the connection is just a perf win; durability comes from sqlite WAL/sync.
    """

    def __init__(self, db_path: Path | str) -> None:
        self._conn = sqlite3.connect(db_path, isolation_level=None)
        # WAL would be nicer for prod but not portable on :memory:; default fine for v0.1.
        self._conn.executescript(_SCHEMA)

    def save(self, decision: Decision) -> int:
        """Insert one Decision row; return its primary-key id."""
        cur = self._conn.execute(
            """
            INSERT INTO decisions (
                batch_id, customer_id, material_name, decided_at,
                action, outcome, savings_estimate,
                actual_savings, actual_qty, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.batch_id,
                decision.customer_id,
                decision.material_name,
                decision.decided_at.isoformat(),
                decision.action.value,
                decision.outcome.value,
                decision.savings_estimate,
                decision.actual_savings,
                decision.actual_qty,
                decision.notes,
            ),
        )
        # autoincrement → lastrowid is the new id
        assert cur.lastrowid is not None  # noqa: S101  (sqlite contract — always set after INSERT)
        return cur.lastrowid

    def list_for_period(
        self,
        customer_id: str,
        start: datetime,
        end: datetime,
    ) -> list[Decision]:
        """Return decisions in [start, end) for this customer, ascending by decided_at.

        Naive datetimes are rejected — mirrors Decision model's invariant so callers
        can't accidentally compare across timezones.
        """
        _require_tz("start", start)
        _require_tz("end", end)

        rows = self._conn.execute(
            """
            SELECT batch_id, customer_id, material_name, decided_at,
                   action, outcome, savings_estimate,
                   actual_savings, actual_qty, notes
            FROM decisions
            WHERE customer_id = ?
              AND decided_at >= ?
              AND decided_at <  ?
            ORDER BY decided_at ASC
            """,
            (customer_id, start.isoformat(), end.isoformat()),
        ).fetchall()

        return [
            Decision(
                batch_id=row[0],
                customer_id=row[1],
                material_name=row[2],
                decided_at=datetime.fromisoformat(row[3]),
                action=ActionType(row[4]),
                outcome=DecisionOutcome(row[5]),
                savings_estimate=row[6],
                actual_savings=row[7],
                actual_qty=row[8],
                notes=row[9],
            )
            for row in rows
        ]
