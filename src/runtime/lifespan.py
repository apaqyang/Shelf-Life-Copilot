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
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI

from src.observability import log_event, metrics
from src.optimization import default_evaluation_cases, evaluate_optimizer
from src.persistence import (
    DecisionRepository,
    DecisionStore,
    IdempotencyRepository,
    IdempotencyStore,
    OptimizationPlanRepository,
    OptimizationPlanStore,
    PostgresDatabase,
    PostgresDecisionStore,
    PostgresIdempotencyStore,
    PostgresOptimizationPlanStore,
    PostgresRateLimiter,
    PostgresRevisionStore,
    PostgresSuggestionStore,
    PostgresWorkOrderStore,
    RevisionRepository,
    RevisionStore,
    SuggestionRepository,
    SuggestionStore,
    WorkOrderRepository,
    WorkOrderStore,
)
from src.plugins import PluginRegistry, load_plugins
from src.reports import ReportRunResult
from src.repository import BatchRepository, PagedERPRepository, SAPBusinessOneClient, get_repository
from src.runtime.config import Settings
from src.runtime.security import OIDCJWTVerifier, SlidingWindowRateLimiter
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
    build_local_provider,
    build_moonshot_provider,
    build_offline_provider,
)
from src.task_queue import DurableTaskQueue, PostgresTaskQueue, TaskWorker
from src.webhook import require_secure_webhook_crypto
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
    if settings.llm_provider == "local":
        return build_local_provider(
            settings.local_llm_base_url,
            model=settings.local_llm_model,
            api_key=settings.local_llm_api_key,
        )
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
            started = time.perf_counter()
            try:
                await client.send_card(card)
            except WecomPushError as exc:
                duration_ms = (time.perf_counter() - started) * 1000
                metrics.increment("push_failure_total")
                log_event(
                    logger,
                    logging.WARNING,
                    "WeCom push failed",
                    customer_id=result.customer_id,
                    correlation_id=result.correlation_id,
                    result="failure",
                    duration_ms=duration_ms,
                    batch_id=card.batch_id,
                    error_type=type(exc).__name__,
                )
            else:
                duration_ms = (time.perf_counter() - started) * 1000
                metrics.increment("push_success_total")
                log_event(
                    logger,
                    logging.INFO,
                    "push.completed",
                    customer_id=result.customer_id,
                    correlation_id=result.correlation_id,
                    result="success",
                    duration_ms=duration_ms,
                    batch_id=card.batch_id,
                )

    return _cb


def build_monthly_callback(
    client: WecomClient,
) -> Callable[[ReportRunResult], Awaitable[None]]:
    """Default on_result for MonthlyReportScheduler — push summary card if data exists."""

    async def _cb(result: ReportRunResult) -> None:
        if result.data is None:
            metrics.increment("report_skipped_total")
            log_event(
                logger,
                logging.INFO,
                "report.skipped",
                customer_id=result.customer_id,
                correlation_id="monthly",
                result="skipped",
                duration_ms=0,
                reason=result.skipped_reason,
            )
            return
        card = render_monthly_summary_card(result.data)
        try:
            await client.send_card(card)
        except WecomPushError as exc:
            metrics.increment("push_failure_total")
            log_event(
                logger,
                logging.WARNING,
                "Monthly push failed",
                customer_id=result.customer_id,
                correlation_id="monthly",
                result="failure",
                duration_ms=0,
                error_type=type(exc).__name__,
            )

    return _cb


def build_lifespan(
    settings: Settings,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Factory returning an asynccontextmanager suitable for `FastAPI(lifespan=...)`."""

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        registry = PluginRegistry(app=app, settings=settings)
        load_plugins(registry)
        require_secure_webhook_crypto(is_development=settings.is_development)
        app.state.loaded_plugins = registry.loaded
        app.state.settings = settings
        if settings.auth_mode == "oidc":
            assert settings.oidc_jwks_url is not None  # noqa: S101 - settings validation
            assert settings.oidc_issuer is not None  # noqa: S101 - settings validation
            assert settings.oidc_audience is not None  # noqa: S101 - settings validation
            app.state.token_verifier = OIDCJWTVerifier(
                jwks_url=settings.oidc_jwks_url,
                issuer=settings.oidc_issuer,
                audience=settings.oidc_audience,
            )
        if registry.loaded:
            logger.info("Enterprise plugins loaded: %s", registry.loaded)
        else:
            logger.info("Pure open-source mode (no enterprise plugins).")

        wecom_client = _build_wecom_client(settings)
        postgres_database: PostgresDatabase | None = None
        decision_store: DecisionRepository
        suggestion_store: SuggestionRepository
        work_order_store: WorkOrderRepository
        idempotency_store: IdempotencyRepository
        revision_store: RevisionRepository
        optimization_plan_store: OptimizationPlanRepository
        task_queue: DurableTaskQueue | PostgresTaskQueue
        if settings.persistence_backend == "postgres":
            assert settings.postgres_dsn is not None  # noqa: S101 - settings validation
            postgres_database = PostgresDatabase.from_dsn(
                settings.postgres_dsn.get_secret_value(),
                min_size=settings.postgres_pool_min_size,
                max_size=settings.postgres_pool_max_size,
            )
            decision_store = PostgresDecisionStore(postgres_database)
            suggestion_store = PostgresSuggestionStore(postgres_database)
            work_order_store = PostgresWorkOrderStore(postgres_database)
            idempotency_store = PostgresIdempotencyStore(postgres_database)
            revision_store = PostgresRevisionStore(postgres_database)
            optimization_plan_store = PostgresOptimizationPlanStore(postgres_database)
            task_queue = PostgresTaskQueue(postgres_database)
            app.state.rate_limiter = PostgresRateLimiter(
                postgres_database,
                limit=settings.rate_limit_requests,
                window_seconds=settings.rate_limit_window_seconds,
            )
        else:
            decision_store = DecisionStore(settings.decisions_db_path)
            suggestion_store = SuggestionStore(settings.decisions_db_path)
            work_order_store = WorkOrderStore(settings.decisions_db_path)
            idempotency_store = IdempotencyStore(settings.decisions_db_path)
            revision_store = RevisionStore(settings.decisions_db_path)
            optimization_plan_store = OptimizationPlanStore(settings.decisions_db_path)
            task_queue = DurableTaskQueue(settings.decisions_db_path)
            app.state.rate_limiter = SlidingWindowRateLimiter(
                limit=settings.rate_limit_requests,
                window_seconds=settings.rate_limit_window_seconds,
            )
        app.state.decision_store = decision_store
        app.state.suggestion_store = suggestion_store
        app.state.work_order_store = work_order_store
        app.state.idempotency_store = idempotency_store
        app.state.revision_store = revision_store
        app.state.optimization_plan_store = optimization_plan_store
        app.state.optimization_gate = evaluate_optimizer(default_evaluation_cases())

        config_repository = get_repository()
        sap_client: SAPBusinessOneClient | None = None
        batch_repository: BatchRepository
        if settings.erp_backend == "sap_b1":
            assert settings.sap_b1_base_url is not None  # noqa: S101 - settings validation

            def sap_session_cookie() -> str:
                if settings.sap_b1_session_cookie_file is not None:
                    cookie = settings.sap_b1_session_cookie_file.read_text(encoding="utf-8").strip()
                else:
                    assert settings.sap_b1_session_cookie is not None  # noqa: S101
                    cookie = settings.sap_b1_session_cookie.get_secret_value()
                if not cookie:
                    raise RuntimeError("SAP session cookie is empty")
                return cookie

            sap_client = SAPBusinessOneClient(
                settings.sap_b1_base_url,
                sap_session_cookie,
                query_code=settings.sap_b1_query_code,
                page_size=settings.sap_b1_page_size,
            )
            batch_repository = PagedERPRepository(
                sap_client,
                config_repository,
                timeout_seconds=settings.sap_b1_timeout_seconds,
                max_retries=settings.sap_b1_max_retries,
            )
        else:
            batch_repository = config_repository
        app.state.batch_repository = batch_repository
        customer_configs = {
            customer_id: batch_repository.load_customer_config(customer_id)
            for customer_id in settings.scan_customers_list
        }
        baselines = settings.customer_baselines or {
            customer_id: config.annual_baseline_loss
            for customer_id, config in customer_configs.items()
        }
        customer_timezones = {
            customer_id: config.business_timezone
            for customer_id, config in customer_configs.items()
        }
        monthly = MonthlyReportScheduler(
            db_path=settings.decisions_db_path,
            output_dir=settings.reports_output_dir,
            baselines=baselines,
            day=settings.monthly_day,
            hour=settings.monthly_hour,
            minute=settings.monthly_minute,
            customer_timezones=customer_timezones,
            decision_repository=decision_store,
            on_result=build_monthly_callback(wecom_client),
        )
        monthly.start()
        app.state.monthly_scheduler = monthly
        logger.info(
            "MonthlyReportScheduler started: day=%d %02d:%02d in tenant business timezones",
            settings.monthly_day,
            settings.monthly_hour,
            settings.monthly_minute,
        )

        provider = _build_provider(settings)
        engine = SuggestionEngine(provider=provider) if provider is not None else None
        runner = ScanRunner(
            engine=engine,
            suggestion_store=suggestion_store,
            max_concurrency=settings.scan_concurrency,
            repository=batch_repository,
        )
        app.state.scan_runner = runner
        app.state.task_queue = task_queue
        task_worker: TaskWorker | None = None
        if provider is None:
            logger.warning(
                "No LLM API key for provider %r; DailyScheduler not started.",
                settings.llm_provider,
            )
            app.state.daily_scheduler = None
        else:
            callback = build_scan_callback(wecom_client)
            if settings.task_queue_enabled:
                task_worker = TaskWorker(
                    task_queue,
                    runner,
                    on_result=callback,
                    max_attempts=settings.task_worker_max_attempts,
                    poll_seconds=settings.task_worker_poll_seconds,
                    visibility_timeout_seconds=settings.task_visibility_timeout_seconds,
                )
                task_worker.start()
            daily = DailyScheduler(
                runner=runner,
                customer_ids=settings.scan_customers_list,
                hour=settings.scan_hour,
                minute=settings.scan_minute,
                customer_timezones=customer_timezones,
                on_result=None if settings.task_queue_enabled else callback,
                task_queue=task_queue if settings.task_queue_enabled else None,
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
            if task_worker is not None:
                await task_worker.stop()
            task_queue.close()
            idempotency_store.close()
            optimization_plan_store.close()
            revision_store.close()
            work_order_store.close()
            suggestion_store.close()
            decision_store.close()
            if sap_client is not None:
                sap_client.close()
            if postgres_database is not None:
                postgres_database.close()
            logger.info("Schedulers shut down cleanly.")

    return _lifespan
