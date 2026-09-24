"""Scan orchestrator — composes load → scan → suggest into one cycle."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.alerts import scan_batch
from src.models import Alert, Batch, Card, Suggestion
from src.observability import log_event, metrics
from src.persistence import SuggestionRepository
from src.repository import BatchRepository, JsonRepository, get_repository
from src.suggestion import SuggestionEngine
from src.wecom import render_card_for_alert

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(UTC)


class ScanError(BaseModel):
    """Recorded LLM-call failure during a scan; lets the runner continue past bad batches."""

    model_config = ConfigDict(frozen=True)

    batch_id: str
    message: str


class ScanResult(BaseModel):
    """Outcome of one full scan cycle for one customer."""

    model_config = ConfigDict(frozen=True)

    customer_id: str
    triggered_at: datetime = Field(default_factory=_now_utc)
    total_batches: int
    alerts: list[Alert]
    suggestions: list[Suggestion]
    cards: list[Card] = Field(default_factory=list)
    errors: list[ScanError]
    batch_ids: list[str] = Field(default_factory=list)
    correlation_id: str = ""
    duration_ms: float = 0.0


class ScanRunner:
    """Orchestrate one scan cycle: load, classify, and (optionally) call the LLM."""

    def __init__(
        self,
        engine: SuggestionEngine | None = None,
        data_root: Path | None = None,
        suggestion_store: SuggestionRepository | None = None,
        repository: BatchRepository | None = None,
        max_concurrency: int = 4,
    ) -> None:
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        self._engine = engine
        self._suggestion_store = suggestion_store
        self._max_concurrency = max_concurrency
        if repository is not None:
            self._repository = repository
        elif data_root is not None:
            self._repository = JsonRepository(data_root)
        else:
            self._repository = get_repository()

    async def run_for_customer(
        self,
        customer_id: str,
        today: date | None = None,
        skip_llm: bool = False,
        correlation_id: str | None = None,
    ) -> ScanResult:
        """Load batches + config, classify severity, optionally call the LLM per alert.

        Args:
            customer_id: which customer to scan
            today: override the date used for days_left calculation (useful for tests)
            skip_llm: when True, returns alerts only — no Claude calls

        Raises:
            ValueError: when skip_llm=False but no engine was injected.
        """
        started = time.perf_counter()
        trace_id = correlation_id or str(uuid4())
        if not skip_llm and self._engine is None:
            raise ValueError("engine is required when skip_llm=False")

        config = self._repository.load_customer_config(customer_id)
        batches = self._repository.load_batches(customer_id)

        alerts: list[Alert] = []
        suggestions: list[Suggestion] = []
        cards: list[Card] = []
        errors: list[ScanError] = []

        alert_batches: list[tuple[Batch, Alert]] = []
        for batch in batches:
            alert = scan_batch(batch, config.alert_thresholds, today=today)
            if alert is None:
                continue
            alerts.append(alert)
            alert_batches.append((batch, alert))

        async def suggest_one(
            batch: Batch, alert: Alert
        ) -> tuple[Suggestion | None, Card | None, ScanError | None]:
            assert self._engine is not None  # noqa: S101 - guarded before scheduling
            try:
                async with semaphore:
                    suggestion = await self._engine.suggest(batch, alert, config)
            except Exception as exc:  # noqa: BLE001
                logger.exception("LLM suggestion failed for batch %s", batch.batch_id)
                return None, None, ScanError(batch_id=batch.batch_id, message=str(exc))
            return suggestion, render_card_for_alert(batch, alert, suggestion, config), None

        if not skip_llm and self._engine is not None:
            semaphore = asyncio.Semaphore(self._max_concurrency)
            outcomes = await asyncio.gather(
                *(suggest_one(batch, alert) for batch, alert in alert_batches)
            )
            for suggestion, card, error in outcomes:
                if error is not None:
                    errors.append(error)
                    continue
                assert suggestion is not None and card is not None  # noqa: S101
                suggestions.append(suggestion)
                cards.append(card)
                if self._suggestion_store is not None:
                    self._suggestion_store.save(suggestion)

        duration_ms = (time.perf_counter() - started) * 1000
        metrics.increment("scan_total")
        metrics.increment("scan_failed_batches_total", len(errors))
        metrics.observe("scan_duration_ms", duration_ms)
        log_event(
            logger,
            logging.INFO,
            "scan.completed",
            customer_id=customer_id,
            correlation_id=trace_id,
            result="partial" if errors else "success",
            duration_ms=duration_ms,
            alert_count=len(alerts),
            suggestion_count=len(suggestions),
        )

        return ScanResult(
            customer_id=customer_id,
            total_batches=len(batches),
            alerts=alerts,
            suggestions=suggestions,
            cards=cards,
            errors=errors,
            batch_ids=[batch.batch_id for batch in batches],
            correlation_id=trace_id,
            duration_ms=duration_ms,
        )

    async def revise_for_batch(
        self,
        customer_id: str,
        batch_id: str,
        feedback: str,
        today: date | None = None,
    ) -> ScanResult:
        """Re-run a suggestion for one batch with operator feedback.

        Mirrors run_for_customer but scoped to a single batch. Out-of-scope
        suggestions still come back rendered (as the red-stamped card) so the
        demo's guard-rail is visible rather than swallowed.

        Raises:
            ValueError: engine not injected.
            KeyError: batch_id not found in the customer's mock data.
        """
        if self._engine is None:
            raise ValueError("engine is required for revise_for_batch")

        config = self._repository.load_customer_config(customer_id)
        batches = self._repository.load_batches(customer_id)

        batch = next((b for b in batches if b.batch_id == batch_id), None)
        if batch is None:
            raise KeyError(batch_id)

        alerts: list[Alert] = []
        suggestions: list[Suggestion] = []
        cards: list[Card] = []
        errors: list[ScanError] = []

        alert = scan_batch(batch, config.alert_thresholds, today=today)
        if alert is not None:
            alerts.append(alert)
            try:
                suggestion = await self._engine.suggest(batch, alert, config, feedback=feedback)
            except Exception as exc:  # noqa: BLE001
                logger.exception("LLM revise failed for batch %s", batch.batch_id)
                errors.append(ScanError(batch_id=batch.batch_id, message=str(exc)))
            else:
                suggestions.append(suggestion)
                cards.append(render_card_for_alert(batch, alert, suggestion, config))
                if self._suggestion_store is not None:
                    self._suggestion_store.save(suggestion)

        return ScanResult(
            customer_id=customer_id,
            total_batches=1,
            alerts=alerts,
            suggestions=suggestions,
            cards=cards,
            errors=errors,
            batch_ids=[batch.batch_id],
        )
