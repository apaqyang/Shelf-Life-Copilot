"""Decision-source loaders feeding the monthly report.

`load_decisions_from_sqlite` is the v0.5 production source; mock-json stays
in the tool layer as the v0.1 fallback while the customer's PoC ramps up.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.models import ActionType, Decision, DecisionOutcome
from src.persistence import DecisionStore
from src.reports.sources import load_decisions_from_sqlite


def _decision(
    *,
    batch_id: str,
    decided_at: datetime,
    customer_id: str = "customerA",
) -> Decision:
    return Decision(
        batch_id=batch_id,
        customer_id=customer_id,
        material_name="冷冻虾仁",
        decided_at=decided_at,
        action=ActionType.TRANSFORM,
        outcome=DecisionOutcome.APPROVED,
        savings_estimate=8500.0,
    )


class TestLoadFromSqlite:
    def test_empty_db_returns_empty_list(self, tmp_path: Path) -> None:
        db_file = tmp_path / "d.db"
        DecisionStore(db_file)  # initialize empty schema
        result = load_decisions_from_sqlite(db_file, "customerA", "2026-05")
        assert result == []

    def test_returns_only_decisions_in_target_month(self, tmp_path: Path) -> None:
        db_file = tmp_path / "d.db"
        store = DecisionStore(db_file)
        store.save(_decision(batch_id="apr", decided_at=datetime(2026, 4, 30, 23, 0, tzinfo=UTC)))
        store.save(_decision(batch_id="may-1", decided_at=datetime(2026, 5, 1, 0, 0, tzinfo=UTC)))
        store.save(
            _decision(batch_id="may-2", decided_at=datetime(2026, 5, 20, 15, 30, tzinfo=UTC))
        )
        store.save(_decision(batch_id="jun", decided_at=datetime(2026, 6, 1, 0, 0, tzinfo=UTC)))

        result = load_decisions_from_sqlite(db_file, "customerA", "2026-05")
        assert [d.batch_id for d in result] == ["may-1", "may-2"]

    def test_filters_by_customer_id(self, tmp_path: Path) -> None:
        db_file = tmp_path / "d.db"
        store = DecisionStore(db_file)
        store.save(
            _decision(
                batch_id="A-1",
                customer_id="customerA",
                decided_at=datetime(2026, 5, 10, tzinfo=UTC),
            )
        )
        store.save(
            _decision(
                batch_id="B-1",
                customer_id="customerB",
                decided_at=datetime(2026, 5, 11, tzinfo=UTC),
            )
        )

        result = load_decisions_from_sqlite(db_file, "customerB", "2026-05")
        assert [d.batch_id for d in result] == ["B-1"]

    def test_december_rolls_into_next_january(self, tmp_path: Path) -> None:
        """Year wrap: 2026-12 must include Dec 31 but exclude Jan 1 of 2027."""
        db_file = tmp_path / "d.db"
        store = DecisionStore(db_file)
        store.save(
            _decision(batch_id="dec-31", decided_at=datetime(2026, 12, 31, 23, 59, tzinfo=UTC))
        )
        store.save(_decision(batch_id="jan-1", decided_at=datetime(2027, 1, 1, 0, 0, tzinfo=UTC)))

        result = load_decisions_from_sqlite(db_file, "customerA", "2026-12")
        assert [d.batch_id for d in result] == ["dec-31"]

    def test_invalid_month_format_raises(self, tmp_path: Path) -> None:
        db_file = tmp_path / "d.db"
        DecisionStore(db_file)
        with pytest.raises(ValueError, match="YYYY-MM"):
            load_decisions_from_sqlite(db_file, "customerA", "2026/05")
        with pytest.raises(ValueError, match="YYYY-MM"):
            load_decisions_from_sqlite(db_file, "customerA", "2026-13")
