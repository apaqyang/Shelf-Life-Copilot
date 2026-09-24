import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from src.scheduler import ScanResult, ScanRunner
from src.task_queue import DurableTaskQueue, TaskStatus, TaskWorker


def test_queue_is_durable_deduplicated_and_stateful(tmp_path: object) -> None:
    path = tmp_path / "queue.db"  # type: ignore[operator]
    now = datetime(2026, 1, 1, tzinfo=UTC)
    queue = DurableTaskQueue(path)
    task_id, created = queue.enqueue("scan", "a", dedupe_key="daily-a", now=now)
    same_id, duplicate = queue.enqueue("scan", "a", dedupe_key="daily-a", now=now)
    assert (same_id, duplicate) == (task_id, False)
    assert created is True
    queue.close()
    assert queue.closed

    queue = DurableTaskQueue(path)
    task = queue.claim(now=now)
    assert task is not None
    assert task.status is TaskStatus.RUNNING
    assert task.attempts == 1
    assert queue.claim(now=now) is None
    queue.complete(task.task_id, now=now)
    assert queue.counts() == {"completed": 1}
    with pytest.raises(ValueError, match="not running"):
        queue.complete(task.task_id, now=now)
    with pytest.raises(ValueError, match="timezone-aware"):
        queue.enqueue("scan", "b", dedupe_key="bad", now=datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="timezone-aware"):
        queue.claim(now=datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="visibility timeout"):
        queue.claim(now=now, visibility_timeout_seconds=0)
    queue.close()


def test_queue_reclaims_expired_worker_lease(tmp_path: object) -> None:
    queue = DurableTaskQueue(tmp_path / "lease.db")  # type: ignore[operator]
    now = datetime(2026, 1, 1, tzinfo=UTC)
    queue.enqueue("scan", "tenant", dedupe_key="lease", now=now)
    first = queue.claim(now=now, visibility_timeout_seconds=300)
    assert first is not None
    assert queue.claim(now=now + timedelta(seconds=299)) is None
    reclaimed = queue.claim(now=now + timedelta(seconds=300))
    assert reclaimed is not None
    assert reclaimed.task_id == first.task_id
    assert reclaimed.attempts == 2
    queue.close()


def test_queue_retries_then_fails(tmp_path: object) -> None:
    queue = DurableTaskQueue(tmp_path / "queue.db")  # type: ignore[operator]
    now = datetime(2026, 1, 1, tzinfo=UTC)
    queue.enqueue("unknown", "a", dedupe_key="retry", now=now)
    first = queue.claim(now=now)
    assert first is not None
    queue.fail(first, "boom", max_attempts=2, now=now)
    assert queue.counts() == {"pending": 1}
    second = queue.claim(now=now + timedelta(seconds=2))
    assert second is not None
    queue.fail(second, "boom", max_attempts=2, now=now)
    assert queue.counts() == {"failed": 1}
    queue.close()


@pytest.mark.asyncio
async def test_worker_completes_and_callbacks() -> None:
    queue = AsyncMock(spec=DurableTaskQueue)
    task = AsyncMock()
    task.task_kind = "scan"
    task.customer_id = "tenant"
    task.task_id = "task"
    queue.claim.return_value = task
    runner = AsyncMock(spec=ScanRunner)
    result = ScanResult(customer_id="tenant", total_batches=0, alerts=[], suggestions=[], errors=[])
    runner.run_for_customer.return_value = result
    callback = AsyncMock()
    worker = TaskWorker(queue, runner, on_result=callback)
    assert await worker.run_once() is True
    queue.complete.assert_called_once_with("task")
    callback.assert_awaited_once_with(result)


@pytest.mark.asyncio
async def test_worker_empty_failure_and_lifecycle(tmp_path: object) -> None:
    queue = DurableTaskQueue(tmp_path / "queue.db")  # type: ignore[operator]
    runner = AsyncMock(spec=ScanRunner)
    worker = TaskWorker(queue, runner, poll_seconds=0.001)
    assert await worker.run_once() is False
    await worker.stop()
    queue.enqueue("scan", "tenant", dedupe_key="good")
    runner.run_for_customer.return_value = ScanResult(
        customer_id="tenant", total_batches=0, alerts=[], suggestions=[], errors=[]
    )
    assert await worker.run_once() is True
    queue.enqueue("unknown", "tenant", dedupe_key="bad")
    assert await worker.run_once() is True
    assert queue.counts() == {"completed": 1, "pending": 1}
    worker = TaskWorker(queue, runner, poll_seconds=0.001)
    worker.start()
    await asyncio.sleep(0.004)
    await worker.stop()
    queue.close()


@pytest.mark.asyncio
async def test_worker_run_loops_after_completed_work(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = AsyncMock(spec=DurableTaskQueue)
    runner = AsyncMock(spec=ScanRunner)
    worker = TaskWorker(queue, runner)
    calls = 0

    async def run_once() -> bool:
        nonlocal calls
        calls += 1
        if calls == 2:
            worker._stop.set()  # noqa: SLF001
        return calls == 1

    monkeypatch.setattr(worker, "run_once", run_once)
    await worker.run()
    assert calls == 2
