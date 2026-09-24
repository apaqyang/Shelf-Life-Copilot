"""Shared SQLite connection policy for all persistence adapters."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import cast

from src.persistence.migrations import run_migrations

DEFAULT_BUSY_TIMEOUT_MS = 5_000
_INITIALIZATION_LOCK = RLock()


class SQLiteDatabase:
    """Thread-safe, explicitly owned SQLite connection."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    ) -> None:
        if busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms must be non-negative")
        self._lock = RLock()
        self._closed = False
        self._connection = sqlite3.connect(
            db_path,
            isolation_level=None,
            check_same_thread=False,
            timeout=busy_timeout_ms / 1_000,
        )
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
        # WAL negotiation and first-run DDL both take database-wide locks.
        # Serialize them inside one process; busy_timeout covers other processes.
        with _INITIALIZATION_LOCK:
            self._connection.execute("PRAGMA journal_mode = WAL")
            self.schema_version = run_migrations(self._connection)

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def busy_timeout_ms(self) -> int:
        with self._lock:
            row = self._connection.execute("PRAGMA busy_timeout").fetchone()
        assert row is not None  # noqa: S101 - PRAGMA always returns one row
        return int(row[0])

    def execute(
        self,
        sql: str,
        parameters: tuple[object, ...] = (),
    ) -> sqlite3.Cursor:
        with self._lock:
            return self._connection.execute(sql, parameters)

    def fetchone(
        self,
        sql: str,
        parameters: tuple[object, ...] = (),
    ) -> tuple[object, ...] | None:
        with self._lock:
            return cast(
                tuple[object, ...] | None,
                self._connection.execute(sql, parameters).fetchone(),
            )

    def fetchall(
        self,
        sql: str,
        parameters: tuple[object, ...] = (),
    ) -> list[tuple[object, ...]]:
        with self._lock:
            return cast(
                list[tuple[object, ...]],
                self._connection.execute(sql, parameters).fetchall(),
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Serialize a transaction on this connection and roll back on failure."""
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True
