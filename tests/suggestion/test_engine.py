"""Tests for SuggestionEngine — uses a mocked AsyncAnthropic client, no real HTTP."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from anthropic import AsyncAnthropic
from anthropic.types import Message, ToolUseBlock
from pydantic import ValidationError

from src.models import ActionType, Alert, AlertThresholds, Batch, CustomerConfig, Severity
from src.suggestion.engine import SuggestionEngine, SuggestionEngineError


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


def _fake_tool_message(
    action: str = "transform",
    savings: float = 8500.0,
    rationale: str = "历史采纳率高，可消化全部库存。",
    confidence: float = 0.85,
    extra_text_block: bool = False,
) -> Message:
    """Construct a fake anthropic Message containing a tool_use block."""
    tool_block = MagicMock(spec=ToolUseBlock)
    tool_block.name = "submit_suggestion"
    tool_block.input = {
        "action": action,
        "savings_estimate": savings,
        "rationale": rationale,
        "confidence": confidence,
    }

    blocks: list[Any] = []
    if extra_text_block:
        text_block = MagicMock()
        blocks.append(text_block)
    blocks.append(tool_block)

    message = MagicMock(spec=Message)
    message.content = blocks
    return message


def _make_engine(message: Message) -> SuggestionEngine:
    client = AsyncMock(spec=AsyncAnthropic)
    client.messages = MagicMock()
    client.messages.create = AsyncMock(return_value=message)
    return SuggestionEngine(client=client)


class TestSuggestionEngineHappyPath:
    @pytest.mark.asyncio
    async def test_returns_standard_suggestion_for_enabled_action(
        self, batch: Batch, alert: Alert, customer: CustomerConfig
    ) -> None:
        engine = _make_engine(_fake_tool_message(action="transform"))
        suggestion = await engine.suggest(batch, alert, customer)

        assert suggestion.action is ActionType.TRANSFORM
        assert suggestion.is_standard is True
        assert suggestion.savings_estimate == 8500.0
        assert suggestion.confidence == 0.85
        assert suggestion.batch_id == "A-001"
        assert suggestion.customer_id == "customerA"
        assert suggestion.llm_model.startswith("claude-")
        assert suggestion.user_feedback is None

    @pytest.mark.asyncio
    async def test_extra_text_blocks_are_ignored(
        self, batch: Batch, alert: Alert, customer: CustomerConfig
    ) -> None:
        engine = _make_engine(_fake_tool_message(extra_text_block=True))
        suggestion = await engine.suggest(batch, alert, customer)
        assert suggestion.action is ActionType.TRANSFORM


class TestSuggestionEngineFeedback:
    @pytest.mark.asyncio
    async def test_feedback_propagated_to_suggestion(
        self, batch: Batch, alert: Alert, customer: CustomerConfig
    ) -> None:
        engine = _make_engine(_fake_tool_message(action="discount_clearance"))
        suggestion = await engine.suggest(batch, alert, customer, feedback="虾饺线满了")
        assert suggestion.user_feedback == "虾饺线满了"
        assert suggestion.action is ActionType.DISCOUNT_CLEARANCE


class TestSuggestionEngineErrorPaths:
    @pytest.mark.asyncio
    async def test_missing_tool_block_raises(
        self, batch: Batch, alert: Alert, customer: CustomerConfig
    ) -> None:
        empty_message = MagicMock(spec=Message)
        empty_message.content = []
        engine = _make_engine(empty_message)

        with pytest.raises(SuggestionEngineError, match="missing tool_use"):
            await engine.suggest(batch, alert, customer)

    @pytest.mark.asyncio
    async def test_non_dict_tool_input_raises(
        self, batch: Batch, alert: Alert, customer: CustomerConfig
    ) -> None:
        bad_block = MagicMock(spec=ToolUseBlock)
        bad_block.name = "submit_suggestion"
        bad_block.input = "not_a_dict"
        bad_message = MagicMock(spec=Message)
        bad_message.content = [bad_block]
        engine = _make_engine(bad_message)

        with pytest.raises(SuggestionEngineError, match="must be a dict"):
            await engine.suggest(batch, alert, customer)

    @pytest.mark.asyncio
    async def test_payload_validation_propagates(
        self, batch: Batch, alert: Alert, customer: CustomerConfig
    ) -> None:
        bad_payload_message = _fake_tool_message(confidence=1.5)  # invalid
        engine = _make_engine(bad_payload_message)
        with pytest.raises(ValidationError):
            await engine.suggest(batch, alert, customer)


class TestSuggestionEngineWiring:
    @pytest.mark.asyncio
    async def test_calls_client_with_expected_tool_choice(
        self, batch: Batch, alert: Alert, customer: CustomerConfig
    ) -> None:
        engine = _make_engine(_fake_tool_message())
        await engine.suggest(batch, alert, customer)

        call_args = engine._client.messages.create.await_args  # type: ignore[attr-defined]
        kwargs = call_args.kwargs
        assert kwargs["tool_choice"] == {"type": "tool", "name": "submit_suggestion"}
        assert kwargs["model"].startswith("claude-")
        assert len(kwargs["tools"]) == 1
        assert kwargs["tools"][0]["name"] == "submit_suggestion"
