"""Tests for SuggestionEngine — uses a mocked LLMProvider, no real HTTP."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from src.models import ActionType, Alert, AlertThresholds, Batch, CustomerConfig, Severity
from src.suggestion.engine import SuggestionEngine, SuggestionEngineError
from src.suggestion.providers import LLMProvider, LLMProviderError


@pytest.fixture
def batch() -> Batch:
    return Batch(
        batch_id="A-001",
        material_id="M-A-001",
        material_name="冷冻虾仁",
        production_date=date(2026, 3, 15),
        expiry_date=date(2026, 6, 14),
        stock_qty=850.0,
        unit="kg",
        warehouse="1号冷库",
        customer_id="customerA",
    )


@pytest.fixture
def alert() -> Alert:
    return Alert(
        batch_id="A-001",
        customer_id="customerA",
        severity=Severity.YELLOW,
        days_left=19,
    )


@pytest.fixture
def customer() -> CustomerConfig:
    return CustomerConfig(
        customer_id="customerA",
        industry="frozen_seafood",
        enabled_actions=[
            ActionType.TRANSFORM,
            ActionType.DISCOUNT_CLEARANCE,
            ActionType.REPORT_LOSS,
        ],
        industry_phrases={ActionType.TRANSFORM: "转加工为虾饺馅"},
        alert_thresholds=AlertThresholds(),
        decision_makers=["userid_1"],
    )


def _make_provider(
    payload: dict[str, object] | None = None,
    *,
    model_name: str = "claude-sonnet-4-6",
    raises: Exception | None = None,
) -> LLMProvider:
    """Build a MagicMock provider returning either a payload or raising."""
    provider = MagicMock(spec=LLMProvider)
    provider.model_name = model_name
    if raises is not None:
        provider.call_with_tool = AsyncMock(side_effect=raises)
    else:
        provider.call_with_tool = AsyncMock(return_value=payload)
    return provider


def _ok_payload(action: str = "transform") -> dict[str, object]:
    return {
        "action": action,
        "savings_estimate": 8500.0,
        "rationale": "历史采纳率高，可消化全部库存。",
        "confidence": 0.85,
    }


class TestSuggestionEngineHappyPath:
    @pytest.mark.asyncio
    async def test_returns_standard_suggestion_for_enabled_action(
        self, batch: Batch, alert: Alert, customer: CustomerConfig
    ) -> None:
        provider = _make_provider(_ok_payload("transform"))
        engine = SuggestionEngine(provider=provider)
        suggestion = await engine.suggest(batch, alert, customer)

        assert suggestion.action is ActionType.TRANSFORM
        assert suggestion.is_standard is True
        assert suggestion.savings_estimate == 8500.0
        assert suggestion.confidence == 0.85
        assert suggestion.batch_id == "A-001"
        assert suggestion.customer_id == "customerA"
        assert suggestion.llm_model == "claude-sonnet-4-6"
        assert suggestion.user_feedback is None

    @pytest.mark.asyncio
    async def test_model_name_taken_from_provider(
        self, batch: Batch, alert: Alert, customer: CustomerConfig
    ) -> None:
        provider = _make_provider(_ok_payload(), model_name="moonshot-v1-32k")
        engine = SuggestionEngine(provider=provider)
        suggestion = await engine.suggest(batch, alert, customer)
        assert suggestion.llm_model == "moonshot-v1-32k"


class TestSuggestionEngineFeedback:
    @pytest.mark.asyncio
    async def test_feedback_propagated_to_suggestion(
        self, batch: Batch, alert: Alert, customer: CustomerConfig
    ) -> None:
        provider = _make_provider(_ok_payload("discount_clearance"))
        engine = SuggestionEngine(provider=provider)
        suggestion = await engine.suggest(batch, alert, customer, feedback="虾饺线满了")
        assert suggestion.user_feedback == "虾饺线满了"
        assert suggestion.action is ActionType.DISCOUNT_CLEARANCE


class TestSuggestionEngineErrorPaths:
    @pytest.mark.asyncio
    async def test_provider_error_wrapped(
        self, batch: Batch, alert: Alert, customer: CustomerConfig
    ) -> None:
        provider = _make_provider(raises=LLMProviderError("transport failed"))
        engine = SuggestionEngine(provider=provider)
        with pytest.raises(SuggestionEngineError, match="transport failed"):
            await engine.suggest(batch, alert, customer)

    @pytest.mark.asyncio
    async def test_payload_validation_propagates(
        self, batch: Batch, alert: Alert, customer: CustomerConfig
    ) -> None:
        bad_payload = {**_ok_payload(), "confidence": 1.5}  # invalid
        provider = _make_provider(bad_payload)
        engine = SuggestionEngine(provider=provider)
        with pytest.raises(ValidationError):
            await engine.suggest(batch, alert, customer)


class TestSuggestionEngineWiring:
    @pytest.mark.asyncio
    async def test_passes_system_user_and_tool_to_provider(
        self, batch: Batch, alert: Alert, customer: CustomerConfig
    ) -> None:
        provider = _make_provider(_ok_payload())
        engine = SuggestionEngine(provider=provider)
        await engine.suggest(batch, alert, customer)

        kwargs = provider.call_with_tool.await_args.kwargs  # type: ignore[union-attr]
        assert "system_prompt" in kwargs
        assert "user_prompt" in kwargs
        assert kwargs["tool_schema"]["name"] == "submit_suggestion"
        # User prompt must include the actual material name (smoke).
        assert "冷冻虾仁" in kwargs["user_prompt"]
        # Tool schema's action enum spans the full action set (PRD §5.3 越界兜底),
        # while the description steers the model toward the customer-enabled subset.
        action_prop = kwargs["tool_schema"]["input_schema"]["properties"]["action"]
        assert "transform" in action_prop["enum"]
        # employee_canteen is disabled for the fixture customer — but still in enum
        # so the LLM can pick it when the user's feedback explicitly asks for it.
        assert "employee_canteen" in action_prop["enum"]
        # The description must list only enabled actions as "preferred".
        assert "transform" in action_prop["description"]
        assert "employee_canteen" not in action_prop["description"]
