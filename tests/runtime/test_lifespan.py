"""FastAPI lifespan tests — verify schedulers boot and shut down cleanly.

We patch APScheduler.start/shutdown when the test doesn't actually need a
running event loop; for the integration test we let TestClient drive the
real lifespan and check what landed on app.state.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.runtime.config import Settings
from src.runtime.lifespan import build_lifespan


@pytest.fixture
def base_settings(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Default Settings pointing at tmp paths so tests never touch repo data."""
    for k in (
        "ANTHROPIC_API_KEY",
        "MOONSHOT_API_KEY",
        "WECOM_WEBHOOK_URL",
        "SCAN_CUSTOMERS",
        "LLM_PROVIDER",
    ):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    s = s.model_copy(
        update={
            "decisions_db_path": tmp_path / "d.db",  # type: ignore[operator]
            "reports_output_dir": tmp_path / "out",  # type: ignore[operator]
        }
    )
    return s


def _make_client(app: FastAPI) -> Iterator[TestClient]:
    """Drive the real lifespan via TestClient context."""
    with TestClient(app) as c:
        yield c


class TestLifespanWithoutLlmKey:
    def test_monthly_scheduler_started_daily_skipped(
        self, base_settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING, logger="src.runtime.lifespan")
        app = FastAPI(lifespan=build_lifespan(base_settings))

        for _ in _make_client(app):
            assert app.state.monthly_scheduler is not None
            assert app.state.daily_scheduler is None

        # WARNING must call out the missing LLM key so ops sees why scan didn't start.
        assert any("LLM" in r.message for r in caplog.records)

    def test_scheduler_reachable_during_lifespan(self, base_settings: Settings) -> None:
        """Inside the lifespan context, the monthly scheduler's jobs are queryable."""
        app = FastAPI(lifespan=build_lifespan(base_settings))
        seen_jobs: list[str] = []
        for _ in _make_client(app):
            seen_jobs = app.state.monthly_scheduler.job_ids
        assert seen_jobs == ["monthly-report"]
        # After context exit, shutdown() has been called; job removal is APScheduler's
        # contract and we don't re-assert it here.


class TestLifespanWithLlmKey:
    def test_daily_scheduler_started_when_provider_key_present(
        self,
        base_settings: Settings,
    ) -> None:
        settings = base_settings.model_copy(update={"anthropic_api_key": "sk-test"})
        app = FastAPI(lifespan=build_lifespan(settings))

        for _ in _make_client(app):
            assert app.state.monthly_scheduler is not None
            assert app.state.daily_scheduler is not None
            # daily scheduler registers one job per customer
            assert set(app.state.daily_scheduler.job_ids) == {
                "scan-customerA",
                "scan-customerB",
            }

    def test_moonshot_provider_path(self, base_settings: Settings) -> None:
        """Provider switch must follow LLM_PROVIDER, not just hard-coded Anthropic."""
        settings = base_settings.model_copy(
            update={
                "llm_provider": "moonshot",
                "moonshot_api_key": "sk-moonshot",
            }
        )
        app = FastAPI(lifespan=build_lifespan(settings))
        for _ in _make_client(app):
            assert app.state.daily_scheduler is not None

    def test_offline_provider_starts_daily_scheduler(self, base_settings: Settings) -> None:
        """offline mode is a valid llm_provider choice for the zero-config demo."""
        settings = base_settings.model_copy(update={"llm_provider": "offline"})
        app = FastAPI(lifespan=build_lifespan(settings))
        for _ in _make_client(app):
            assert app.state.daily_scheduler is not None  # NOT None, even sans key

    def test_webhook_url_uses_real_client(self, base_settings: Settings) -> None:
        """When WECOM_WEBHOOK_URL is set, the WeCom client must be WebhookWecomClient."""
        from src.wecom import WebhookWecomClient

        settings = base_settings.model_copy(update={"wecom_webhook_url": "https://example.com/k"})
        # Drive _build_wecom_client directly so we don't actually emit HTTP.
        from src.runtime.lifespan import _build_wecom_client

        client = _build_wecom_client(settings)
        assert isinstance(client, WebhookWecomClient)


class TestSchedulerLifecycleHooks:
    def test_lifespan_calls_start_and_shutdown_on_both(
        self,
        base_settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If the scheduler factory hands back our mock, lifespan must drive it."""
        from src.runtime import lifespan as ls_mod

        # Mock both scheduler classes so we can capture start/shutdown calls.
        mock_monthly = MagicMock()
        mock_monthly.job_ids = ["monthly-report"]
        mock_daily = MagicMock()
        mock_daily.job_ids = ["scan-customerA"]

        monkeypatch.setattr(ls_mod, "MonthlyReportScheduler", lambda **_kw: mock_monthly)
        monkeypatch.setattr(ls_mod, "DailyScheduler", lambda **_kw: mock_daily)

        settings = base_settings.model_copy(update={"anthropic_api_key": "sk-test"})
        app = FastAPI(lifespan=build_lifespan(settings))

        for _ in _make_client(app):
            mock_monthly.start.assert_called_once()
            mock_daily.start.assert_called_once()

        # After TestClient context exit, shutdown must have been called too.
        mock_monthly.shutdown.assert_called_once()
        mock_daily.shutdown.assert_called_once()


class TestPluginSeam:
    """The lifespan loads enterprise plugins, defaulting to pure open-source mode."""

    def test_pure_oss_mode_when_no_plugins(
        self, base_settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO, logger="src.runtime.lifespan")
        app = FastAPI(lifespan=build_lifespan(base_settings))
        for _ in _make_client(app):
            assert app.state.loaded_plugins == []
        assert any("open-source mode" in r.message for r in caplog.records)

    def test_loaded_plugins_logged(
        self,
        base_settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from pathlib import Path

        from src.plugins import PluginRegistry
        from src.runtime import lifespan as ls_mod

        def fake_load(registry: PluginRegistry, plugins_root: Path | None = None) -> list[str]:
            registry.loaded.append("erp_sap")
            return registry.loaded

        monkeypatch.setattr(ls_mod, "load_plugins", fake_load)
        caplog.set_level(logging.INFO, logger="src.runtime.lifespan")
        app = FastAPI(lifespan=build_lifespan(base_settings))
        for _ in _make_client(app):
            assert app.state.loaded_plugins == ["erp_sap"]
        assert any("Enterprise plugins loaded" in r.message for r in caplog.records)


class TestPushCallbacks:
    """Default callbacks push to the configured WeCom client (Webhook or DryRun)."""

    @pytest.mark.asyncio
    async def test_scan_callback_pushes_each_card(self, base_settings: Settings) -> None:
        from src.models import Alert, Card, CardKind, Severity
        from src.runtime.lifespan import build_scan_callback
        from src.scheduler import ScanResult

        client = AsyncMock()
        cb = build_scan_callback(client)

        card = Card(
            kind=CardKind.ALERT,
            customer_id="customerA",
            batch_id="A-001",
            title="t",
            markdown="## body",
        )
        result = ScanResult(
            customer_id="customerA",
            total_batches=1,
            alerts=[
                Alert(
                    batch_id="A-001",
                    customer_id="customerA",
                    severity=Severity.YELLOW,
                    days_left=19,
                )
            ],
            suggestions=[],
            cards=[card, card.model_copy(update={"batch_id": "A-002"})],
            errors=[],
        )
        await cb(result)
        assert client.send_card.await_count == 2

    @pytest.mark.asyncio
    async def test_monthly_callback_pushes_summary_card(self, base_settings: Settings) -> None:
        from datetime import UTC, datetime

        from src.models import ActionType
        from src.reports import ReportRunResult
        from src.reports.aggregator import ActionTally, MonthlyReportData
        from src.runtime.lifespan import build_monthly_callback

        client = AsyncMock()
        cb = build_monthly_callback(client)

        data = MonthlyReportData(
            customer_id="customerA",
            industry="frozen_seafood",
            month="2026-05",
            total_count=2,
            approved_count=2,
            approval_rate=1.0,
            total_savings_estimate=14000.0,
            total_savings_actual=14000.0,
            top_actions=[
                ActionTally(
                    action=ActionType.TRANSFORM,
                    approved_count=1,
                    total_actual_savings=8200.0,
                )
            ],
            case_studies=[],
            annual_baseline_loss=1_500_000.0,
            monthly_subscription_fee=12500.0,
            roi_multiple=1.12,
            generated_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
        result = ReportRunResult(
            customer_id="customerA",
            pdf_path=None,
            data=data,
            skipped_reason=None,
        )
        await cb(result)
        assert client.send_card.await_count == 1

    @pytest.mark.asyncio
    async def test_scan_callback_logs_warning_on_push_failure(
        self,
        base_settings: Settings,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from src.models import Alert, Card, CardKind, Severity
        from src.runtime.lifespan import build_scan_callback
        from src.scheduler import ScanResult
        from src.wecom import WecomPushError

        client = AsyncMock()
        client.send_card = AsyncMock(side_effect=WecomPushError("oops"))
        cb = build_scan_callback(client)

        result = ScanResult(
            customer_id="customerA",
            total_batches=1,
            alerts=[
                Alert(
                    batch_id="A-001",
                    customer_id="customerA",
                    severity=Severity.YELLOW,
                    days_left=19,
                )
            ],
            suggestions=[],
            cards=[
                Card(
                    kind=CardKind.ALERT,
                    customer_id="customerA",
                    batch_id="A-001",
                    title="t",
                    markdown="## b",
                )
            ],
            errors=[],
        )
        caplog.set_level(logging.WARNING, logger="src.runtime.lifespan")
        await cb(result)
        assert any("push failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_monthly_callback_logs_warning_on_push_failure(
        self,
        base_settings: Settings,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from datetime import UTC, datetime

        from src.reports import ReportRunResult
        from src.reports.aggregator import MonthlyReportData
        from src.runtime.lifespan import build_monthly_callback
        from src.wecom import WecomPushError

        client = AsyncMock()
        client.send_card = AsyncMock(side_effect=WecomPushError("nope"))
        cb = build_monthly_callback(client)

        data = MonthlyReportData(
            customer_id="customerA",
            industry="frozen_seafood",
            month="2026-05",
            total_count=1,
            approved_count=1,
            approval_rate=1.0,
            total_savings_estimate=100.0,
            total_savings_actual=100.0,
            top_actions=[],
            case_studies=[],
            annual_baseline_loss=1_000_000.0,
            monthly_subscription_fee=10000.0,
            roi_multiple=0.01,
            generated_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
        caplog.set_level(logging.WARNING, logger="src.runtime.lifespan")
        await cb(
            ReportRunResult(
                customer_id="customerA",
                pdf_path=None,
                data=data,
                skipped_reason=None,
            )
        )
        assert any("push failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_monthly_callback_skips_when_no_data(self, base_settings: Settings) -> None:
        from src.reports import ReportRunResult
        from src.runtime.lifespan import build_monthly_callback

        client = AsyncMock()
        cb = build_monthly_callback(client)
        await cb(
            ReportRunResult(
                customer_id="customerA",
                pdf_path=None,
                data=None,
                skipped_reason="no decisions",
            )
        )
        client.send_card.assert_not_awaited()
