"""Daily cron wrapper — triggers ScanRunner for each registered customer at fixed hour."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.observability import log_event, metrics
from src.scheduler.runner import ScanResult, ScanRunner

logger = logging.getLogger(__name__)

ScanResultCallback = Callable[[ScanResult], Awaitable[None]]


class TaskPublisher(Protocol):
    def enqueue(
        self,
        task_kind: str,
        customer_id: str,
        *,
        payload: dict[str, object] | None = None,
        dedupe_key: str,
        now: datetime | None = None,
    ) -> tuple[str, bool]: ...  # pragma: no cover


class DailyScheduler:
    """Run ScanRunner for each customer at a fixed time each day.

    Construction registers one APScheduler job per customer. Call `start()` to
    begin firing (requires a running asyncio event loop), and `shutdown()` to stop.
    """

    def __init__(
        self,
        runner: ScanRunner,
        customer_ids: list[str],
        hour: int = 7,
        minute: int = 0,
        timezone: str = "Asia/Shanghai",
        on_result: ScanResultCallback | None = None,
        task_queue: TaskPublisher | None = None,
    ) -> None:
        if not customer_ids:
            raise ValueError("customer_ids must not be empty")
        if not 0 <= hour <= 23:
            raise ValueError(f"hour must be 0..23, got {hour}")
        if not 0 <= minute <= 59:
            raise ValueError(f"minute must be 0..59, got {minute}")

        self._runner = runner
        self._customer_ids = customer_ids
        self._hour = hour
        self._minute = minute
        self._timezone = timezone
        self._on_result = on_result
        self._task_queue = task_queue
        self._scheduler = AsyncIOScheduler()
        self._register_jobs()

    def _register_jobs(self) -> None:
        for customer_id in self._customer_ids:
            self._scheduler.add_job(
                self._run_one_customer,
                trigger=CronTrigger(
                    hour=self._hour,
                    minute=self._minute,
                    timezone=self._timezone,
                ),
                args=[customer_id],
                id=f"scan-{customer_id}",
                replace_existing=True,
            )

    async def _run_one_customer(self, customer_id: str) -> None:
        if self._task_queue is not None:
            business_date = datetime.now(ZoneInfo(self._timezone)).date().isoformat()
            self._task_queue.enqueue(
                "scan",
                customer_id,
                dedupe_key=f"scan:{customer_id}:{business_date}",
            )
            return
        started = time.perf_counter()
        try:
            result = await self._runner.run_for_customer(customer_id)
        except Exception:  # noqa: BLE001
            duration_ms = (time.perf_counter() - started) * 1000
            metrics.increment("scan_failure_total")
            log_event(
                logger,
                logging.ERROR,
                "scan.failed",
                customer_id=customer_id,
                correlation_id="scheduler",
                result="failure",
                duration_ms=duration_ms,
            )
            return

        metrics.increment("scan_success_total" if not result.errors else "scan_partial_total")
        log_event(
            logger,
            logging.INFO,
            "scan.dispatched",
            customer_id=customer_id,
            correlation_id=result.correlation_id,
            result="partial" if result.errors else "success",
            duration_ms=result.duration_ms,
            alert_count=len(result.alerts),
            suggestion_count=len(result.suggestions),
            error_count=len(result.errors),
        )
        if self._on_result is not None:
            await self._on_result(result)

    def start(self) -> None:
        """Begin firing scheduled jobs (requires a running asyncio event loop)."""
        self._scheduler.start()

    def shutdown(self, wait: bool = True) -> None:
        """Stop the scheduler. Safe to call when not running."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)

    @property
    def job_ids(self) -> list[str]:
        """IDs of all registered jobs (one per customer)."""
        jobs = self._scheduler.get_jobs()
        return [job.id for job in jobs]
