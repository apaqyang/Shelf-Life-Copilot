"""Monthly cron wrapper — fires run_monthly_reports once per month.

Mirrors DailyScheduler's "register one APScheduler job, dispatch to a callback"
shape so operations folks see one scheduler pattern across the codebase, not
two. The cron defaults to day 1 at 08:00 Asia/Shanghai so each run can
generate and deliver the previous calendar month's report.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.observability import log_event, metrics
from src.reports import ReportRunResult, run_monthly_reports

logger = logging.getLogger(__name__)

ReportResultCallback = Callable[[ReportRunResult], Awaitable[None]]

_JOB_ID = "monthly-report"


class MonthlyReportScheduler:
    """Run `run_monthly_reports` on a monthly cron, dispatch each result to a callback.

    Construction registers one APScheduler job; call `start()` to begin firing
    (requires a running asyncio event loop), `shutdown()` to stop. Use
    `run_now()` to invoke the body once for manual triggering / testing.
    """

    def __init__(
        self,
        *,
        db_path: Path | str,
        output_dir: Path,
        baselines: dict[str, float],
        day: int = 1,
        hour: int = 8,
        minute: int = 0,
        timezone: str = "Asia/Shanghai",
        on_result: ReportResultCallback | None = None,
    ) -> None:
        # day capped at 28 so we never hit a non-existent calendar day (Feb 29/30/31).
        if not 1 <= day <= 28:
            raise ValueError(f"day must be 1..28, got {day}")
        if not 0 <= hour <= 23:
            raise ValueError(f"hour must be 0..23, got {hour}")
        if not 0 <= minute <= 59:
            raise ValueError(f"minute must be 0..59, got {minute}")

        self._db_path = db_path
        self._output_dir = output_dir
        self._baselines = baselines
        self._on_result = on_result
        self._timezone = ZoneInfo(timezone)
        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self.run_now,
            trigger=CronTrigger(day=day, hour=hour, minute=minute, timezone=self._timezone),
            id=_JOB_ID,
            replace_existing=True,
        )

    async def run_now(self) -> None:
        """Trigger one report cycle: aggregate → PDF → fan-out callbacks.

        Wraps the orchestrator in a broad try/except so a sqlite glitch or PDF
        failure doesn't bring down APScheduler's reactor — operations folks
        check logs and re-run via this same method.
        """
        started = time.perf_counter()
        try:
            results = run_monthly_reports(
                today=datetime.now(self._timezone).date(),
                db_path=self._db_path,
                output_dir=self._output_dir,
                baselines=self._baselines,
            )
        except Exception:  # noqa: BLE001
            duration_ms = (time.perf_counter() - started) * 1000
            metrics.increment("report_failure_total")
            metrics.observe("report_duration_ms", duration_ms)
            log_event(
                logger,
                logging.ERROR,
                "report.failed",
                customer_id="all",
                correlation_id="monthly",
                result="failure",
                duration_ms=duration_ms,
            )
            return

        duration_ms = (time.perf_counter() - started) * 1000
        metrics.increment("report_success_total")
        metrics.observe("report_duration_ms", duration_ms)
        log_event(
            logger,
            logging.INFO,
            "report.completed",
            customer_id="all",
            correlation_id="monthly",
            result="success",
            duration_ms=duration_ms,
            report_count=len(results),
            skipped_count=sum(1 for r in results if r.is_skipped),
        )

        if self._on_result is None:
            return

        for result in results:
            try:
                await self._on_result(result)
            except Exception:  # noqa: BLE001
                log_event(
                    logger,
                    logging.ERROR,
                    "report.callback_failed",
                    customer_id=result.customer_id,
                    correlation_id="monthly",
                    result="failure",
                    duration_ms=0,
                )

    def start(self) -> None:
        """Begin firing the monthly job (requires a running asyncio event loop)."""
        self._scheduler.start()

    def shutdown(self, wait: bool = True) -> None:
        """Stop the scheduler. Safe to call when not running."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)

    @property
    def job_ids(self) -> list[str]:
        return [job.id for job in self._scheduler.get_jobs()]
