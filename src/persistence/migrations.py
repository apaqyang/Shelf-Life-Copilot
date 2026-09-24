"""Versioned, transactional SQLite schema migrations."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Migration:
    """One atomic schema change."""

    version: int
    name: str
    statements: tuple[str, ...]


MIGRATIONS: Final[tuple[Migration, ...]] = (
    Migration(
        version=1,
        name="decision_and_suggestion_baseline",
        statements=(
            """
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
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_decisions_customer_period
                ON decisions(customer_id, decided_at)
            """,
            """
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
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_suggestions_lookup
                ON suggestions(customer_id, batch_id, generated_at DESC)
            """,
        ),
    ),
    Migration(
        version=2,
        name="approval_work_orders",
        statements=(
            "ALTER TABLE decisions ADD COLUMN idempotency_key TEXT",
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_decisions_idempotency
                ON decisions(idempotency_key)
                WHERE idempotency_key IS NOT NULL
            """,
            """
            CREATE TABLE work_orders (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                work_order_id     TEXT    NOT NULL UNIQUE,
                decision_id       INTEGER NOT NULL UNIQUE,
                batch_id          TEXT    NOT NULL,
                customer_id       TEXT    NOT NULL,
                material_name     TEXT    NOT NULL,
                action            TEXT    NOT NULL,
                status            TEXT    NOT NULL,
                created_at        TEXT    NOT NULL,
                updated_at        TEXT    NOT NULL,
                FOREIGN KEY(decision_id) REFERENCES decisions(id) ON DELETE RESTRICT,
                UNIQUE(customer_id, batch_id)
            )
            """,
            """
            CREATE INDEX idx_work_orders_customer_status
                ON work_orders(customer_id, status, created_at)
            """,
        ),
    ),
    Migration(
        version=3,
        name="work_order_receipts",
        statements=(
            "ALTER TABLE work_orders ADD COLUMN actual_qty REAL",
            "ALTER TABLE work_orders ADD COLUMN actual_savings REAL",
            "ALTER TABLE work_orders ADD COLUMN completed_by TEXT",
            "ALTER TABLE work_orders ADD COLUMN completed_at TEXT",
            "ALTER TABLE work_orders ADD COLUMN completion_source TEXT",
        ),
    ),
    Migration(
        version=4,
        name="request_idempotency",
        statements=(
            """
            CREATE TABLE idempotency_records (
                idempotency_key  TEXT PRIMARY KEY,
                request_kind     TEXT NOT NULL,
                status           TEXT NOT NULL,
                status_code      INTEGER,
                response_json    TEXT,
                created_at       TEXT NOT NULL,
                completed_at     TEXT
            )
            """,
            """
            CREATE INDEX idx_idempotency_created
                ON idempotency_records(request_kind, created_at)
            """,
        ),
    ),
    Migration(
        version=5,
        name="revision_audit_sessions",
        statements=(
            """
            CREATE TABLE revision_sessions (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                operator_id           TEXT NOT NULL,
                customer_id           TEXT NOT NULL,
                batch_id              TEXT NOT NULL,
                original_generated_at TEXT NOT NULL,
                feedback              TEXT,
                feedback_event_id     TEXT,
                revised_generated_at  TEXT,
                status                TEXT NOT NULL,
                created_at            TEXT NOT NULL,
                UNIQUE(customer_id, batch_id, original_generated_at)
            )
            """,
            """
            CREATE UNIQUE INDEX idx_revision_operator_pending
            ON revision_sessions(operator_id)
            WHERE status = 'pending'
            """,
        ),
    ),
    Migration(
        version=6,
        name="optimization_plans",
        statements=(
            """
            CREATE TABLE optimization_plans (
                plan_id       TEXT PRIMARY KEY,
                customer_id   TEXT NOT NULL,
                request_json  TEXT NOT NULL,
                result_json   TEXT NOT NULL,
                status        TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                approved_by   TEXT,
                approved_at   TEXT
            )
            """,
            """
            CREATE INDEX idx_optimization_plans_customer
                ON optimization_plans(customer_id, created_at DESC)
            """,
        ),
    ),
    Migration(
        version=7,
        name="durable_task_queue",
        statements=(
            """
            CREATE TABLE task_queue (
                task_id       TEXT PRIMARY KEY,
                task_kind     TEXT NOT NULL,
                customer_id   TEXT NOT NULL,
                payload_json  TEXT NOT NULL,
                status        TEXT NOT NULL,
                attempts      INTEGER NOT NULL DEFAULT 0,
                available_at  TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                claimed_at    TEXT,
                completed_at  TEXT,
                last_error    TEXT,
                dedupe_key    TEXT NOT NULL UNIQUE
            )
            """,
            """
            CREATE INDEX idx_task_queue_claim
                ON task_queue(status, available_at, created_at)
            """,
        ),
    ),
)

LATEST_SCHEMA_VERSION: Final[int] = MIGRATIONS[-1].version


def run_migrations(
    connection: sqlite3.Connection,
    migrations: tuple[Migration, ...] = MIGRATIONS,
) -> int:
    """Apply pending migrations and return the resulting schema version.

    Each migration and its version marker share one transaction. A failed
    statement therefore cannot leave a partially upgraded schema behind.
    """
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     INTEGER PRIMARY KEY,
                name        TEXT NOT NULL,
                applied_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    previous = 0
    for migration in migrations:
        if migration.version <= previous:
            raise ValueError("migration versions must be strictly increasing")
        previous = migration.version
        connection.execute("BEGIN IMMEDIATE")
        try:
            already_applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                (migration.version,),
            ).fetchone()
            if already_applied is not None:
                connection.commit()
                continue
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                (migration.version, migration.name),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    row = connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    assert row is not None  # noqa: S101 - aggregate queries always return one row
    return int(row[0])
