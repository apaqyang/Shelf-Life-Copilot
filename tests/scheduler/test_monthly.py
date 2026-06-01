"""MonthlyReportScheduler — verify job registration, validation, and dispatch.

We don't drive APScheduler's clock; we just check it's wired up correctly and
that manual invocation of the job body does the right thing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from apscheduler.triggers.cron import CronTrigger

from src.models import ActionType, Decision, DecisionOutcome
from src.persistence import DecisionStore
from src.reports import ReportRunResult
from src.scheduler.monthly import MonthlyReportScheduler


def _decision(decided_at: datetime) -> Decision:
    return Decision(
        batch_id="A-001",
        customer_id="customerA",
        material_name="冷冻虾仁",
        decided_at=decided_at,
        action=ActionType.TRANSFORM,
        outcome=DecisionOutcome.APPROVED,
        savings_estimate=8500.0,
        actual_savings=8200.0,
        actual_qty=100.0,
    )


@pytest.fixture
def populated_db(tmp_path: Path) -> Path:
    db = tmp_path / "d.db"
    store = DecisionStore(db)
    # Run-time-anchored: scheduler uses datetime.now() to pick the "previous"
    # month, so seed a decision into _that_ window so the test is stable.
    now = datetime.now(UTC)
    last_month_year = now.year if now.month > 1 else now.year - 1
    last_month = now.month - 1 if now.month > 1 else 12
    store.save(_decision(datetime(last_month_year, last_month, 15, 12, 0, tzinfo=UTC)))
    return db


class TestInit:
    def test_validates_day(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="day"):
            MonthlyReportScheduler(
                db_path=tmp_path / "d.db",
                output_dir=tmp_path / "out",
                baselines={"customerA": 1.0},
                day=0,
            )
        with pytest.raises(ValueError, match="day"):
            MonthlyReportScheduler(
                db_path=tmp_path / "d.db",
                output_dir=tmp_path / "out",
                baselines={"customerA": 1.0},
                day=29,
            )

    def test_validates_hour_minute(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="hour"):
            MonthlyReportScheduler(
                db_path=tmp_path / "d.db",
                output_dir=tmp_path / "out",
                baselines={"customerA": 1.0},
                hour=24,
            )
        with pytest.raises(ValueError, match="minute"):
            MonthlyReportScheduler(
                db_path=tmp_path / "d.db",
                output_dir=tmp_path / "out",
                baselines={"customerA": 1.0},
                minute=60,
            )

    def test_registers_single_monthly_job(self, tmp_path: Path) -> None:
        sched = MonthlyReportScheduler(
            db_path=tmp_path / "d.db",
            output_dir=tmp_path / "out",
            baselines={"customerA": 1.0},
        )
        assert sched.job_ids == ["monthly-report"]

    def test_cron_trigger_defaults_to_day1_08_00_shanghai(self, tmp_path: Path) -> None:
        sched = MonthlyReportScheduler(
            db_path=tmp_path / "d.db",
            output_dir=tmp_path / "out",
            baselines={"customerA": 1.0},
        )
        job = sched._scheduler.get_job("monthly-report")
        assert job is not None
        trigger = job.trigger
        assert isinstance(trigger, CronTrigger)
        fields = {f.name: str(f) for f in trigger.fields}
        assert fields["day"] == "1"
        assert fields["hour"] == "8"
        assert fields["minute"] == "0"
        assert str(trigger.timezone) == "Asia/Shanghai"


class TestRun:
    @pytest.mark.asyncio
    async def test_run_now_invokes_on_result_for_each_non_skipped(
        self, populated_db: Path, tmp_path: Path
    ) -> None:
        seen: list[ReportRunResult] = []

        async def _cb(r: ReportRunResult) -> None:
            seen.append(r)

        sched = MonthlyReportScheduler(
            db_path=populated_db,
            output_dir=tmp_path / "out",
            baselines={"customerA": 1_500_000.0, "customerB": 860_000.0},
            on_result=_cb,
        )
        await sched.run_now()

        # customerA has the seeded decision → not skipped; customerB empty → skipped.
        # on_result fires for all results so the caller can decide what to do
        # with skipped ones (e.g. send a "no activity" message).
        assert {r.customer_id for r in seen} == {"customerA", "customerB"}
        a = next(r for r in seen if r.customer_id == "customerA")
        assert not a.is_skipped
        assert a.pdf_path is not None and a.pdf_path.exists()

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_abort_other_customers(
        self, populated_db: Path, tmp_path: Path
    ) -> None:
        call_count = {"n": 0}

        async def _flaky(r: ReportRunResult) -> None:
            call_count["n"] += 1
            if r.customer_id == "customerA":
                raise RuntimeError("simulated wecom push failure")

        sched = MonthlyReportScheduler(
            db_path=populated_db,
            output_dir=tmp_path / "out",
            baselines={"customerA": 1_500_000.0, "customerB": 860_000.0},
            on_result=_flaky,
        )
        await sched.run_now()
        assert call_count["n"] == 2  # B still got its callback

    @pytest.mark.asyncio
    async def test_run_now_without_callback_is_noop_safe(
        self, populated_db: Path, tmp_path: Path
    ) -> None:
        sched = MonthlyReportScheduler(
            db_path=populated_db,
            output_dir=tmp_path / "out",
            baselines={"customerA": 1_500_000.0},
            # no on_result
        )
        await sched.run_now()  # should not raise

    @pytest.mark.asyncio
    async def test_run_orchestration_failure_logged_not_raised(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If run_monthly_reports itself blows up, scheduler must absorb the error."""
        import src.scheduler.monthly as monthly_mod

        def _boom(**_kw: object) -> list[ReportRunResult]:
            raise RuntimeError("boom")

        monkeypatch.setattr(monthly_mod, "run_monthly_reports", _boom)

        seen = AsyncMock()
        sched = MonthlyReportScheduler(
            db_path=tmp_path / "d.db",
            output_dir=tmp_path / "out",
            baselines={"customerA": 1_500_000.0},
            on_result=seen,
        )
        await sched.run_now()
        seen.assert_not_awaited()


class TestLifecycle:
    def test_shutdown_noop_when_not_running(self, tmp_path: Path) -> None:
        sched = MonthlyReportScheduler(
            db_path=tmp_path / "d.db",
            output_dir=tmp_path / "out",
            baselines={"customerA": 1.0},
        )
        sched.shutdown()  # must not raise

    @pytest.mark.asyncio
    async def test_start_then_shutdown_cycle(self, tmp_path: Path) -> None:
        """start() requires a running event loop; pytest-asyncio gives us one.

        We don't assert on `running` after shutdown — AsyncIOScheduler clears
        the flag via the event loop, which may not have ticked yet by the time
        shutdown() returns. Verifying both calls don't raise is enough coverage
        for the lifecycle methods.
        """
        sched = MonthlyReportScheduler(
            db_path=tmp_path / "d.db",
            output_dir=tmp_path / "out",
            baselines={"customerA": 1.0},
        )
        sched.start()
        assert sched._scheduler.running
        sched.shutdown()
