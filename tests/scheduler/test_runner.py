"""Tests for ScanRunner — uses real mock data + mocked SuggestionEngine."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest

from src.models import (
    ActionType,
    Alert,
    Batch,
    CustomerConfig,
    Severity,
    Suggestion,
)
from src.scheduler import ScanResult, ScanRunner
from src.suggestion import SuggestionEngine
from src.suggestion.engine import SuggestionEngineError


def _make_suggestion(
    batch_id: str,
    customer_id: str = "customerA",
    action: ActionType = ActionType.TRANSFORM,
) -> Suggestion:
    return Suggestion(
        batch_id=batch_id,
        customer_id=customer_id,
        action=action,
        savings_estimate=8500.0,
        rationale="模拟建议",
        confidence=0.8,
        is_standard=True,
        llm_model="claude-sonnet-4-6",
    )


@pytest.fixture
def mock_engine() -> AsyncMock:
    engine = AsyncMock(spec=SuggestionEngine)

    async def _suggest(
        batch: Batch, alert: Alert, customer: CustomerConfig, feedback: str | None = None
    ) -> Suggestion:
        return _make_suggestion(batch.batch_id, customer.customer_id)

    engine.suggest = AsyncMock(side_effect=_suggest)
    return engine


class TestScanRunnerCustomerA:
    """Use real customerA mock data (data/batches/customerA.json)."""

    @pytest.mark.asyncio
    async def test_alerts_match_expected_severity_distribution(
        self, mock_engine: AsyncMock
    ) -> None:
        runner = ScanRunner(engine=mock_engine)
        result = await runner.run_for_customer("customerA", today=date(2026, 5, 26))

        # customerA has 7 batches; A-004 (鲍鱼 / 60d) is healthy → 6 alerts expected
        assert result.total_batches == 7
        assert len(result.alerts) == 6
        assert len(result.suggestions) == 6
        assert result.errors == []

        # Verify severity distribution from the mock data
        severities = [a.severity for a in result.alerts]
        assert severities.count(Severity.RED) >= 2  # 墨鱼 5d + 虾饺皮 已过期
        assert severities.count(Severity.YELLOW) >= 2  # 虾仁 19d + 虾仁 25d
        assert Severity.ORANGE in severities

    @pytest.mark.asyncio
    async def test_skip_llm_returns_alerts_only(self, mock_engine: AsyncMock) -> None:
        runner = ScanRunner(engine=mock_engine)
        result = await runner.run_for_customer("customerA", today=date(2026, 5, 26), skip_llm=True)

        assert len(result.alerts) == 6
        assert result.suggestions == []
        mock_engine.suggest.assert_not_awaited()


class TestScanRunnerCustomerB:
    """customerB uses tighter thresholds 14/7/3 — different alert distribution."""

    @pytest.mark.asyncio
    async def test_uses_tighter_thresholds(self, mock_engine: AsyncMock) -> None:
        runner = ScanRunner(engine=mock_engine)
        result = await runner.run_for_customer("customerB", today=date(2026, 5, 26))

        # customerB has 6 batches; B-004 (剩余 25d > 14d) is healthy → 5 alerts
        assert result.total_batches == 6
        assert len(result.alerts) == 5


class TestScanRunnerErrorIsolation:
    @pytest.mark.asyncio
    async def test_llm_failure_recorded_does_not_abort(self) -> None:
        engine = AsyncMock(spec=SuggestionEngine)

        # First call fails, subsequent calls succeed
        call_count = {"n": 0}

        async def _flaky_suggest(
            batch: Batch, alert: Alert, customer: CustomerConfig, feedback: str | None = None
        ) -> Suggestion:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise SuggestionEngineError("simulated transient failure")
            return _make_suggestion(batch.batch_id, customer.customer_id)

        engine.suggest = AsyncMock(side_effect=_flaky_suggest)

        runner = ScanRunner(engine=engine)
        result = await runner.run_for_customer("customerA", today=date(2026, 5, 26))

        assert len(result.errors) == 1
        assert result.errors[0].message == "simulated transient failure"
        assert len(result.suggestions) == 5  # 6 alerts - 1 failure


class TestScanRunnerOptionalEngine:
    @pytest.mark.asyncio
    async def test_engine_none_with_skip_llm_works(self) -> None:
        runner = ScanRunner(engine=None)
        result = await runner.run_for_customer("customerA", today=date(2026, 5, 26), skip_llm=True)
        assert len(result.alerts) == 6
        assert result.suggestions == []

    @pytest.mark.asyncio
    async def test_engine_none_without_skip_llm_raises(self) -> None:
        runner = ScanRunner(engine=None)
        with pytest.raises(ValueError, match="engine is required"):
            await runner.run_for_customer("customerA", today=date(2026, 5, 26))


class TestScanResultModel:
    def test_scan_result_frozen(self) -> None:
        result = ScanResult(
            customer_id="customerA",
            total_batches=0,
            alerts=[],
            suggestions=[],
            cards=[],
            errors=[],
        )
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            result.customer_id = "customerB"  # type: ignore[misc]


class TestScanRunnerCardRendering:
    """ScanRunner renders a Card per successful suggestion."""

    @pytest.mark.asyncio
    async def test_one_card_per_suggestion(self, mock_engine: AsyncMock) -> None:
        runner = ScanRunner(engine=mock_engine)
        result = await runner.run_for_customer("customerA", today=date(2026, 5, 26))
        assert len(result.cards) == len(result.suggestions) == 6
        assert all(c.is_standard for c in result.cards)

    @pytest.mark.asyncio
    async def test_no_cards_when_skip_llm(self, mock_engine: AsyncMock) -> None:
        runner = ScanRunner(engine=mock_engine)
        result = await runner.run_for_customer("customerA", today=date(2026, 5, 26), skip_llm=True)
        assert result.cards == []

    @pytest.mark.asyncio
    async def test_out_of_scope_suggestion_routes_to_red_card(self) -> None:
        from src.models.card import CardKind

        engine = AsyncMock(spec=SuggestionEngine)

        async def _suggest(
            batch: Batch, alert: Alert, customer: CustomerConfig, feedback: str | None = None
        ) -> Suggestion:
            # employee_canteen is in customerA's disabled_actions
            return Suggestion(
                batch_id=batch.batch_id,
                customer_id=customer.customer_id,
                action=ActionType.EMPLOYEE_CANTEEN,
                savings_estimate=2000.0,
                rationale="员工内部消化",
                confidence=0.7,
                is_standard=False,
                llm_model="claude-haiku-4-5",
            )

        engine.suggest = AsyncMock(side_effect=_suggest)
        runner = ScanRunner(engine=engine)
        result = await runner.run_for_customer("customerA", today=date(2026, 5, 26))
        assert all(c.kind is CardKind.OUT_OF_SCOPE for c in result.cards)
        assert all(not c.is_standard for c in result.cards)

    @pytest.mark.asyncio
    async def test_failed_suggestion_yields_no_card(self) -> None:
        engine = AsyncMock(spec=SuggestionEngine)
        engine.suggest = AsyncMock(side_effect=SuggestionEngineError("boom"))
        runner = ScanRunner(engine=engine)
        result = await runner.run_for_customer("customerA", today=date(2026, 5, 26))
        assert result.cards == []
        assert len(result.errors) == 6
