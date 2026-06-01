"""Decision-source loaders for the monthly report.

Two sources ship in v0.1:
- mock JSON files (tool-layer convenience, used while no real decision log exists)
- SQLite via DecisionStore (production path; this becomes the only source in v0.5)

The mock-json loader lives in the tool script itself since it's I/O-only and
not reused elsewhere; the sqlite loader earns its own home here because the
month → [start, end) conversion has off-by-one risk and deserves tests.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from src.models import Decision
from src.persistence import DecisionStore

_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def _parse_month(month: str) -> tuple[int, int]:
    """Parse 'YYYY-MM' into (year, month) ints. Strict — rejects '2026-13' / '2026/05'."""
    m = _MONTH_RE.match(month)
    if not m:
        raise ValueError(f"month must be YYYY-MM (1-12), got {month!r}")
    return int(m.group(1)), int(m.group(2))


def load_decisions_from_sqlite(
    db_path: Path | str,
    customer_id: str,
    month: str,
) -> list[Decision]:
    """Read all decisions for `customer_id` whose `decided_at` falls in `month`.

    Window is [start_of_month, start_of_next_month) in UTC. Year-wraps correctly
    for December → January. The store enforces tz-aware boundaries.
    """
    year, mo = _parse_month(month)
    start = datetime(year, mo, 1, tzinfo=UTC)
    end_year = year + (1 if mo == 12 else 0)
    end_mo = 1 if mo == 12 else mo + 1
    end = datetime(end_year, end_mo, 1, tzinfo=UTC)
    return DecisionStore(db_path).list_for_period(customer_id, start, end)
