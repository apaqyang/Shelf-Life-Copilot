"""Scan orchestrator — composes load → scan → suggest into one cycle."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from src.alerts import scan_batch
from src.models import Alert, Card, Suggestion
from src.persistence import SuggestionStore
from src.repository import load_batches, load_customer_config
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


class ScanRunner:
    """Orchestrate one scan cycle: load, classify, and (optionally) call the LLM."""

    def __init__(
        self,
        engine: SuggestionEngine | None = None,
        data_root: Path | None = None,
        suggestion_store: SuggestionStore | None = None,
    ) -> None:
        self._engine = engine
        self._data_root = data_root
        self._suggestion_store = suggestion_store

    async def run_for_customer(
        self,
        customer_id: str,
        today: date | None = None,
        skip_llm: bool = False,
    ) -> ScanResult:
        """Load batches + config, classify severity, optionally call the LLM per alert.

        Args:
            customer_id: which customer to scan
            today: override the date used for days_left calculation (useful for tests)
            skip_llm: when True, returns alerts only — no Claude calls

        Raises:
            ValueError: when skip_llm=False but no engine was injected.
        """
        if not skip_llm and self._engine is None:
            raise ValueError("engine is required when skip_llm=False")

        config = load_customer_config(customer_id, root=self._data_root)
        batches = load_batches(customer_id, root=self._data_root)

        alerts: list[Alert] = []
        suggestions: list[Suggestion] = []
        cards: list[Card] = []
        errors: list[ScanError] = []

        for batch in batches:
            alert = scan_batch(batch, config.alert_thresholds, today=today)
            if alert is None:
                continue
            alerts.append(alert)

            if skip_llm or self._engine is None:
                continue

            # Per-batch isolation: one bad LLM call must not abort the whole scan.
            try:
                suggestion = await self._engine.suggest(batch, alert, config)
            except Exception as exc:  # noqa: BLE001
                logger.exception("LLM suggestion failed for batch %s", batch.batch_id)
                errors.append(ScanError(batch_id=batch.batch_id, message=str(exc)))
                continue
            suggestions.append(suggestion)
            cards.append(render_card_for_alert(batch, alert, suggestion, config))
            if self._suggestion_store is not None:
                self._suggestion_store.save(suggestion)

        return ScanResult(
            customer_id=customer_id,
            total_batches=len(batches),
            alerts=alerts,
            suggestions=suggestions,
            cards=cards,
            errors=errors,
        )

    async def revise_for_batch(
        self,
        customer_id: str,
        batch_id: str,
        feedback: str,
        today: date | None = None,
    ) -> ScanResult:
        """Re-run suggestion for one batch with operator feedback (PRD §5.3 改方案).

        Mirrors run_for_customer but scoped to a single batch. Out-of-scope
        suggestions still come back rendered (as the red-stamped card) so the
        demo's guard-rail is visible rather than swallowed.

        Raises:
            ValueError: engine not injected.
            KeyError: batch_id not found in the customer's mock data.
        """
        if self._engine is None:
            raise ValueError("engine is required for revise_for_batch")

        config = load_customer_config(customer_id, root=self._data_root)
        batches = load_batches(customer_id, root=self._data_root)

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
        )
