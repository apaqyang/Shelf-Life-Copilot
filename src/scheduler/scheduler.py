"""Daily cron wrapper — triggers ScanRunner for each registered customer at fixed hour."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.scheduler.runner import ScanResult, ScanRunner

logger = logging.getLogger(__name__)

ScanResultCallback = Callable[[ScanResult], Awaitable[None]]


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
        on_result: ScanResultCallback | None = None,
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
        self._on_result = on_result
        self._scheduler = AsyncIOScheduler()
        self._register_jobs()

    def _register_jobs(self) -> None:
        for customer_id in self._customer_ids:
            self._scheduler.add_job(
                self._run_one_customer,
                trigger=CronTrigger(hour=self._hour, minute=self._minute),
                args=[customer_id],
                id=f"scan-{customer_id}",
                replace_existing=True,
            )

    async def _run_one_customer(self, customer_id: str) -> None:
        try:
            result = await self._runner.run_for_customer(customer_id)
        except Exception:  # noqa: BLE001
            logger.exception("Scan job failed for customer %s", customer_id)
            return

        logger.info(
            "Scan %s: %d alerts, %d suggestions, %d errors",
            customer_id,
            len(result.alerts),
            len(result.suggestions),
            len(result.errors),
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
