"""Monthly cron wrapper — fires run_monthly_reports once per month.

Mirrors DailyScheduler's "register one APScheduler job, dispatch to a callback"
shape so operations folks see one scheduler pattern across the codebase, not
two. The cron defaults (day=1, 08:00 Asia/Shanghai) match PRD §5.5: "每月 1 号
自动生成上一月 PDF 报告，企微推送给总监".
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

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
        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self.run_now,
            trigger=CronTrigger(day=day, hour=hour, minute=minute, timezone=timezone),
            id=_JOB_ID,
            replace_existing=True,
        )

    async def run_now(self) -> None:
        """Trigger one report cycle: aggregate → PDF → fan-out callbacks.

        Wraps the orchestrator in a broad try/except so a sqlite glitch or PDF
        failure doesn't bring down APScheduler's reactor — operations folks
        check logs and re-run via this same method.
        """
        try:
            results = run_monthly_reports(
                today=datetime.now(UTC).date(),
                db_path=self._db_path,
                output_dir=self._output_dir,
                baselines=self._baselines,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Monthly report orchestration failed")
            return

        logger.info(
            "Monthly run produced %d results (skipped=%d)",
            len(results),
            sum(1 for r in results if r.is_skipped),
        )

        if self._on_result is None:
            return

        for result in results:
            try:
                await self._on_result(result)
            except Exception:  # noqa: BLE001
                logger.exception("Monthly on_result callback failed for %s", result.customer_id)

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
