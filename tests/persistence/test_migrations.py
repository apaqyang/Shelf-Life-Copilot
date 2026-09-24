"""SQLite migration runner and connection-policy tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.persistence import LATEST_SCHEMA_VERSION, DecisionStore
from src.persistence.migrations import Migration, run_migrations
from src.persistence.sqlite import SQLiteDatabase


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def test_new_database_reaches_latest_version_and_reopen_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "new.db"
    with DecisionStore(path) as store:
        assert store.schema_version == LATEST_SCHEMA_VERSION
    with DecisionStore(path) as reopened:
        assert reopened.schema_version == LATEST_SCHEMA_VERSION
    with sqlite3.connect(path) as connection:
        assert {"schema_migrations", "decisions", "suggestions", "work_orders"} <= _tables(
            connection
        )


def test_unversioned_legacy_database_is_upgraded_without_data_loss(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT NOT NULL,
                customer_id TEXT NOT NULL, material_name TEXT NOT NULL,
                decided_at TEXT NOT NULL, action TEXT NOT NULL, outcome TEXT NOT NULL,
                savings_estimate REAL NOT NULL, actual_savings REAL,
                actual_qty REAL, notes TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO decisions (
                batch_id, customer_id, material_name, decided_at,
                action, outcome, savings_estimate
            ) VALUES ('A-OLD', 'customerA', 'legacy', '2026-09-01T00:00:00+00:00',
                      'transform', 'approved', 1.0)
            """
        )
    with DecisionStore(path) as store:
        assert store.schema_version == LATEST_SCHEMA_VERSION
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT batch_id FROM decisions").fetchone() == ("A-OLD",)
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(decisions)")}
        assert "idempotency_key" in columns


def test_failed_migration_rolls_back_its_schema_changes() -> None:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    broken = Migration(
        version=1,
        name="broken",
        statements=("CREATE TABLE half_done(id INTEGER)", "INVALID SQL"),
    )
    with pytest.raises(sqlite3.OperationalError):
        run_migrations(connection, (broken,))
    assert "half_done" not in _tables(connection)
    assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone() == (0,)


def test_migration_versions_must_be_strictly_increasing() -> None:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    migrations = (
        Migration(1, "first", ("CREATE TABLE first(id INTEGER)",)),
        Migration(1, "duplicate", ()),
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        run_migrations(connection, migrations)


def test_bootstrap_failure_is_rolled_back() -> None:
    connection = MagicMock(spec=sqlite3.Connection)
    connection.execute.side_effect = sqlite3.OperationalError("read only")
    with pytest.raises(sqlite3.OperationalError, match="read only"):
        run_migrations(connection)
    connection.rollback.assert_called_once()


def test_sqlite_connection_policy_and_transaction_rollback() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        SQLiteDatabase(":memory:", busy_timeout_ms=-1)

    database = SQLiteDatabase(":memory:", busy_timeout_ms=1234)
    assert database.busy_timeout_ms == 1234
    database.execute("CREATE TABLE sample(value TEXT)")
    assert database.fetchone("SELECT value FROM sample") is None
    with database.transaction() as connection:
        connection.execute("INSERT INTO sample VALUES ('kept')")
    with pytest.raises(RuntimeError, match="rollback"), database.transaction() as connection:
        connection.execute("INSERT INTO sample VALUES ('lost')")
        raise RuntimeError("rollback")
    assert database.fetchall("SELECT value FROM sample") == [("kept",)]
    database.close()
    database.close()
    assert database.closed
