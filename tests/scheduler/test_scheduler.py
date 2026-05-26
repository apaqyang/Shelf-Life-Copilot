"""Tests for DailyScheduler — verify job registration + dispatch, not real cron firing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.scheduler import DailyScheduler, ScanResult, ScanRunner


def _make_scan_result(customer_id: str = "customerA") -> ScanResult:
    return ScanResult(
        customer_id=customer_id,
        total_batches=0,
        alerts=[],
        suggestions=[],
        errors=[],
    )


@pytest.fixture
def runner() -> AsyncMock:
    mock = AsyncMock(spec=ScanRunner)
    mock.run_for_customer = AsyncMock(side_effect=lambda cid: _make_scan_result(cid))
    return mock


class TestDailySchedulerInit:
    def test_registers_one_job_per_customer(self, runner: AsyncMock) -> None:
        scheduler = DailyScheduler(runner=runner, customer_ids=["customerA", "customerB"])
        assert set(scheduler.job_ids) == {"scan-customerA", "scan-customerB"}

    def test_empty_customer_ids_rejected(self, runner: AsyncMock) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            DailyScheduler(runner=runner, customer_ids=[])

    def test_hour_out_of_range_rejected(self, runner: AsyncMock) -> None:
        with pytest.raises(ValueError, match="hour must be 0..23"):
            DailyScheduler(runner=runner, customer_ids=["customerA"], hour=24)

    def test_minute_out_of_range_rejected(self, runner: AsyncMock) -> None:
        with pytest.raises(ValueError, match="minute must be 0..59"):
            DailyScheduler(runner=runner, customer_ids=["customerA"], minute=-1)


class TestDailySchedulerDispatch:
    @pytest.mark.asyncio
    async def test_run_one_customer_calls_runner(self, runner: AsyncMock) -> None:
        scheduler = DailyScheduler(runner=runner, customer_ids=["customerA"])
        await scheduler._run_one_customer("customerA")  # noqa: SLF001
        runner.run_for_customer.assert_awaited_once_with("customerA")

    @pytest.mark.asyncio
    async def test_on_result_callback_invoked(self, runner: AsyncMock) -> None:
        on_result = AsyncMock()
        scheduler = DailyScheduler(
            runner=runner,
            customer_ids=["customerA"],
            on_result=on_result,
        )
        await scheduler._run_one_customer("customerA")  # noqa: SLF001
        on_result.assert_awaited_once()
        passed = on_result.await_args.args[0]
        assert passed.customer_id == "customerA"

    @pytest.mark.asyncio
    async def test_runner_error_is_swallowed(self) -> None:
        broken_runner = AsyncMock(spec=ScanRunner)
        broken_runner.run_for_customer = AsyncMock(side_effect=RuntimeError("boom"))
        on_result = AsyncMock()

        scheduler = DailyScheduler(
            runner=broken_runner,
            customer_ids=["customerA"],
            on_result=on_result,
        )
        # Should not raise — error is logged + swallowed; on_result NOT called.
        await scheduler._run_one_customer("customerA")  # noqa: SLF001
        on_result.assert_not_awaited()


class TestDailySchedulerLifecycle:
    def test_shutdown_when_not_running_is_safe(self, runner: AsyncMock) -> None:
        scheduler = DailyScheduler(runner=runner, customer_ids=["customerA"])
        # APScheduler hasn't been started → shutdown should no-op without raising
        scheduler.shutdown()

    def test_start_and_shutdown_lifecycle(
        self, runner: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Avoid touching real APScheduler state by replacing the internal scheduler.
        fake_internal = MagicMock()
        fake_internal.running = False
        fake_internal.get_jobs = MagicMock(return_value=[])
        scheduler = DailyScheduler(runner=runner, customer_ids=["customerA"])
        monkeypatch.setattr(scheduler, "_scheduler", fake_internal)

        scheduler.start()
        fake_internal.start.assert_called_once()

        fake_internal.running = True
        scheduler.shutdown(wait=False)
        fake_internal.shutdown.assert_called_once_with(wait=False)
