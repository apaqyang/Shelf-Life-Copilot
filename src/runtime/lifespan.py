"""FastAPI lifespan: boot DailyScheduler + MonthlyReportScheduler on startup.

Wired at import time in `src/main.py` so `uvicorn src.main:app` is sufficient
to bring the whole v0.1 service up.

Failure model:
- No LLM key → log WARNING, skip DailyScheduler, keep monthly + webhook alive
- No WeCom webhook URL → cards land in DryRunWecomClient (in-memory)
- Scheduler internal failures → swallowed by the schedulers themselves so
  the FastAPI event loop never goes down with a stack trace
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI

from src.persistence import SuggestionStore
from src.plugins import PluginRegistry, load_plugins
from src.reports import ReportRunResult
from src.runtime.config import Settings
from src.scheduler import (
    DailyScheduler,
    MonthlyReportScheduler,
    ScanResult,
    ScanRunner,
)
from src.suggestion import (
    ANTHROPIC_DEFAULT_MODEL,
    MOONSHOT_DEFAULT_MODEL,
    LLMProvider,
    SuggestionEngine,
    build_anthropic_provider,
    build_moonshot_provider,
    build_offline_provider,
)
from src.wecom import (
    DryRunWecomClient,
    WebhookWecomClient,
    WecomClient,
    WecomPushError,
    render_monthly_summary_card,
)

logger = logging.getLogger(__name__)


def _build_provider(settings: Settings) -> LLMProvider | None:
    """Construct the LLM provider for the configured key, or None if missing."""
    if settings.llm_provider == "offline":
        return build_offline_provider()
    if settings.active_llm_key is None:
        return None
    if settings.llm_provider == "anthropic":
        return build_anthropic_provider(settings.active_llm_key, model=ANTHROPIC_DEFAULT_MODEL)
    return build_moonshot_provider(settings.active_llm_key, model=MOONSHOT_DEFAULT_MODEL)


def _build_wecom_client(settings: Settings) -> WecomClient:
    if settings.wecom_webhook_url:
        return WebhookWecomClient(settings.wecom_webhook_url)
    logger.info("WECOM_WEBHOOK_URL unset; cards will go to DryRunWecomClient (in-memory).")
    return DryRunWecomClient()


def build_scan_callback(
    client: WecomClient,
) -> Callable[[ScanResult], Awaitable[None]]:
    """Default on_result for DailyScheduler — push every rendered card to WeCom."""

    async def _cb(result: ScanResult) -> None:
        for card in result.cards:
            try:
                await client.send_card(card)
            except WecomPushError as exc:
                logger.warning(
                    "WeCom push failed for %s batch=%s: %s",
                    result.customer_id,
                    card.batch_id,
                    exc,
                )

    return _cb


def build_monthly_callback(
    client: WecomClient,
) -> Callable[[ReportRunResult], Awaitable[None]]:
    """Default on_result for MonthlyReportScheduler — push summary card if data exists."""

    async def _cb(result: ReportRunResult) -> None:
        if result.data is None:
            logger.info(
                "Monthly skip for %s: %s",
                result.customer_id,
                result.skipped_reason,
            )
            return
        card = render_monthly_summary_card(result.data)
        try:
            await client.send_card(card)
        except WecomPushError as exc:
            logger.warning("Monthly summary push failed for %s: %s", result.customer_id, exc)

    return _cb


def build_lifespan(
    settings: Settings,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Factory returning an asynccontextmanager suitable for `FastAPI(lifespan=...)`."""

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        registry = PluginRegistry(app=app, settings=settings)
        load_plugins(registry)
        app.state.loaded_plugins = registry.loaded
        if registry.loaded:
            logger.info("Enterprise plugins loaded: %s", registry.loaded)
        else:
            logger.info("Pure open-source mode (no enterprise plugins).")

        wecom_client = _build_wecom_client(settings)

        monthly = MonthlyReportScheduler(
            db_path=settings.decisions_db_path,
            output_dir=settings.reports_output_dir,
            baselines=settings.customer_baselines,
            day=settings.monthly_day,
            hour=settings.monthly_hour,
            minute=settings.monthly_minute,
            on_result=build_monthly_callback(wecom_client),
        )
        monthly.start()
        app.state.monthly_scheduler = monthly
        logger.info(
            "MonthlyReportScheduler started: day=%d %02d:%02d Asia/Shanghai",
            settings.monthly_day,
            settings.monthly_hour,
            settings.monthly_minute,
        )

        provider = _build_provider(settings)
        if provider is None:
            logger.warning(
                "No LLM API key for provider %r; DailyScheduler not started.",
                settings.llm_provider,
            )
            app.state.daily_scheduler = None
        else:
            # Share the decisions DB file with both stores — two tables, one sqlite.
            suggestion_store = SuggestionStore(settings.decisions_db_path)
            runner = ScanRunner(
                engine=SuggestionEngine(provider=provider),
                suggestion_store=suggestion_store,
            )
            daily = DailyScheduler(
                runner=runner,
                customer_ids=settings.scan_customers_list,
                hour=settings.scan_hour,
                minute=settings.scan_minute,
                on_result=build_scan_callback(wecom_client),
            )
            daily.start()
            app.state.daily_scheduler = daily
            logger.info(
                "DailyScheduler started: %02d:%02d for customers %s",
                settings.scan_hour,
                settings.scan_minute,
                settings.scan_customers_list,
            )

        try:
            yield
        finally:
            monthly.shutdown()
            daily_sched = app.state.daily_scheduler
            if daily_sched is not None:
                daily_sched.shutdown()
            logger.info("Schedulers shut down cleanly.")

    return _lifespan
