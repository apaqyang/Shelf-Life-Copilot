"""SQLite-backed durable queue separating cron dispatch from scan execution."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from src.persistence.sqlite import SQLiteDatabase
from src.scheduler.runner import ScanResult, ScanRunner


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class QueuedTask(BaseModel):
    model_config = ConfigDict(frozen=True)
    task_id: str
    task_kind: str
    customer_id: str
    payload: dict[str, object]
    status: TaskStatus
    attempts: int


class DurableTaskQueue:
    def __init__(self, db_path: Path | str) -> None:
        self._db = SQLiteDatabase(db_path)

    @property
    def closed(self) -> bool:
        return self._db.closed

    def close(self) -> None:
        self._db.close()

    def enqueue(
        self,
        task_kind: str,
        customer_id: str,
        *,
        payload: dict[str, object] | None = None,
        dedupe_key: str,
        now: datetime | None = None,
    ) -> tuple[str, bool]:
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None:
            raise ValueError("queue timestamp must be timezone-aware")
        task_id = str(uuid4())
        cursor = self._db.execute(
            """INSERT OR IGNORE INTO task_queue
               (task_id, task_kind, customer_id, payload_json, status,
                available_at, created_at, dedupe_key)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task_id,
                task_kind,
                customer_id,
                json.dumps(payload or {}, separators=(",", ":")),
                TaskStatus.PENDING.value,
                instant.astimezone(UTC).isoformat(),
                instant.astimezone(UTC).isoformat(),
                dedupe_key,
            ),
        )
        if cursor.rowcount == 1:
            return task_id, True
        row = self._db.fetchone(
            "SELECT task_id FROM task_queue WHERE dedupe_key = ?", (dedupe_key,)
        )
        assert row is not None  # noqa: S101 - ignored insert means the key exists
        return str(row[0]), False

    def claim(
        self, *, now: datetime | None = None, visibility_timeout_seconds: int = 300
    ) -> QueuedTask | None:
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None:
            raise ValueError("queue timestamp must be timezone-aware")
        if visibility_timeout_seconds <= 0:
            raise ValueError("visibility timeout must be positive")
        with self._db.transaction() as connection:
            stale_before = instant - timedelta(seconds=visibility_timeout_seconds)
            connection.execute(
                """UPDATE task_queue
                   SET status = ?, available_at = ?, claimed_at = NULL
                   WHERE status = ? AND claimed_at <= ?""",
                (
                    TaskStatus.PENDING.value,
                    instant.astimezone(UTC).isoformat(),
                    TaskStatus.RUNNING.value,
                    stale_before.astimezone(UTC).isoformat(),
                ),
            )
            row = connection.execute(
                """SELECT task_id, task_kind, customer_id, payload_json, status, attempts
                   FROM task_queue
                   WHERE status = ? AND available_at <= ?
                   ORDER BY created_at, task_id LIMIT 1""",
                (TaskStatus.PENDING.value, instant.astimezone(UTC).isoformat()),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """UPDATE task_queue SET status = ?, attempts = attempts + 1, claimed_at = ?
                   WHERE task_id = ?""",
                (TaskStatus.RUNNING.value, instant.astimezone(UTC).isoformat(), row[0]),
            )
        return _task_from_row((*row[:4], TaskStatus.RUNNING.value, int(row[5]) + 1))

    def complete(self, task_id: str, *, now: datetime | None = None) -> None:
        instant = now or datetime.now(UTC)
        cursor = self._db.execute(
            "UPDATE task_queue SET status = ?, completed_at = ? WHERE task_id = ? AND status = ?",
            (
                TaskStatus.COMPLETED.value,
                instant.astimezone(UTC).isoformat(),
                task_id,
                TaskStatus.RUNNING.value,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("task is not running")

    def fail(
        self,
        task: QueuedTask,
        error: str,
        *,
        max_attempts: int,
        now: datetime | None = None,
    ) -> None:
        instant = now or datetime.now(UTC)
        retry = task.attempts < max_attempts
        status = TaskStatus.PENDING if retry else TaskStatus.FAILED
        available = instant + timedelta(seconds=min(60, 2**task.attempts))
        self._db.execute(
            """UPDATE task_queue SET status = ?, available_at = ?, last_error = ?
               WHERE task_id = ? AND status = ?""",
            (
                status.value,
                available.astimezone(UTC).isoformat(),
                error[:500],
                task.task_id,
                TaskStatus.RUNNING.value,
            ),
        )

    def counts(self) -> dict[str, int]:
        rows = self._db.fetchall("SELECT status, COUNT(*) FROM task_queue GROUP BY status")
        return {str(row[0]): int(str(row[1])) for row in rows}


def _task_from_row(row: tuple[object, ...]) -> QueuedTask:
    return QueuedTask(
        task_id=str(row[0]),
        task_kind=str(row[1]),
        customer_id=str(row[2]),
        payload=json.loads(str(row[3])),
        status=TaskStatus(str(row[4])),
        attempts=int(str(row[5])),
    )


class TaskWorker:
    def __init__(
        self,
        queue: DurableTaskQueue,
        runner: ScanRunner,
        *,
        on_result: Callable[[ScanResult], Awaitable[None]] | None = None,
        max_attempts: int = 3,
        poll_seconds: float = 0.2,
        visibility_timeout_seconds: int = 300,
    ) -> None:
        self._queue = queue
        self._runner = runner
        self._on_result = on_result
        self._max_attempts = max_attempts
        self._poll_seconds = poll_seconds
        self._visibility_timeout_seconds = visibility_timeout_seconds
        self._stop = asyncio.Event()
        self._background: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._background = asyncio.create_task(self.run())

    async def stop(self) -> None:
        self._stop.set()
        if self._background is not None:
            await self._background

    async def run_once(self) -> bool:
        task = self._queue.claim(visibility_timeout_seconds=self._visibility_timeout_seconds)
        if task is None:
            return False
        try:
            if task.task_kind != "scan":
                raise ValueError(f"unsupported task kind: {task.task_kind}")
            result = await self._runner.run_for_customer(task.customer_id)
            if self._on_result is not None:
                await self._on_result(result)
        except Exception as exc:  # noqa: BLE001
            self._queue.fail(task, str(exc), max_attempts=self._max_attempts)
        else:
            self._queue.complete(task.task_id)
        return True

    async def run(self) -> None:
        while not self._stop.is_set():
            if not await self.run_once():
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
