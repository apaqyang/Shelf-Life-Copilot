"""OfflineLLMProvider — deterministic mock used by the self-service试用 (包 A).

Why this exists:
- Lets a food-plant IT lead clone the repo, `docker-compose up`, and see a real
  WeCom card flow in their terminal in 5 minutes — no Anthropic key, no
  Moonshot key, no signup.
- Same LLMProvider Protocol as the real providers, so SuggestionEngine doesn't
  branch on offline mode anywhere.
"""

from __future__ import annotations

import pytest

from src.models import ActionType
from src.suggestion.providers import (
    LLMProvider,
    OfflineLLMProvider,
    build_offline_provider,
)
from src.suggestion.schema import build_suggestion_tool


class TestOfflineProvider:
    def test_implements_protocol(self) -> None:
        p: LLMProvider = OfflineLLMProvider()
        assert hasattr(p, "call_with_tool")
        assert p.model_name == "offline-demo"

    @pytest.mark.asyncio
    async def test_returns_first_enabled_action_from_tool_schema(self) -> None:
        """Offline provider must pick an in-scope action so is_standard=True."""
        provider = OfflineLLMProvider()
        tool = build_suggestion_tool([ActionType.DISCOUNT_CLEARANCE, ActionType.REPORT_LOSS])

        result = await provider.call_with_tool(
            system_prompt="ignored",
            user_prompt="ignored",
            tool_schema=tool,
        )
        assert result["action"] == ActionType.DISCOUNT_CLEARANCE.value
        assert result["savings_estimate"] > 0
        assert isinstance(result["rationale"], str) and result["rationale"]
        assert 0.0 < result["confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_action_changes_when_enabled_set_changes(self) -> None:
        """Different customers (different enabled_actions) → different suggestion."""
        provider = OfflineLLMProvider()

        tool_a = build_suggestion_tool([ActionType.TRANSFORM])
        result_a = await provider.call_with_tool("", "", tool_a)
        tool_b = build_suggestion_tool([ActionType.EMPLOYEE_CANTEEN])
        result_b = await provider.call_with_tool("", "", tool_b)

        assert result_a["action"] == ActionType.TRANSFORM.value
        assert result_b["action"] == ActionType.EMPLOYEE_CANTEEN.value

    @pytest.mark.asyncio
    async def test_rationale_explains_demo_mode(self) -> None:
        """Don't pretend an LLM ran — be explicit in the rationale text."""
        provider = OfflineLLMProvider()
        tool = build_suggestion_tool([ActionType.TRANSFORM])
        result = await provider.call_with_tool("", "", tool)
        assert "演示" in result["rationale"] or "demo" in result["rationale"].lower()


class TestErrorBranches:
    """Bad schema → useful errors, not cryptic stack traces."""

    @pytest.mark.asyncio
    async def test_missing_description_raises(self) -> None:
        from src.suggestion.providers import LLMProviderError

        provider = OfflineLLMProvider()
        bad_schema = {"input_schema": {"properties": {"action": {}}}}  # no description
        with pytest.raises(LLMProviderError, match="action.description"):
            await provider.call_with_tool("", "", bad_schema)

    @pytest.mark.asyncio
    async def test_description_without_enabled_hint_raises(self) -> None:
        from src.suggestion.providers import LLMProviderError

        provider = OfflineLLMProvider()
        bad_schema = {
            "input_schema": {
                "properties": {"action": {"description": "no hint string here"}},
            },
        }
        with pytest.raises(LLMProviderError, match="enabled-actions hint"):
            await provider.call_with_tool("", "", bad_schema)

    @pytest.mark.asyncio
    async def test_empty_enabled_list_raises(self) -> None:
        from src.suggestion.providers import LLMProviderError

        provider = OfflineLLMProvider()
        bad_schema = {
            "input_schema": {
                "properties": {"action": {"description": "customer-enabled actions: [ , , ]"}},
            },
        }
        with pytest.raises(LLMProviderError, match="at least one"):
            await provider.call_with_tool("", "", bad_schema)


class TestBuildHelper:
    def test_build_offline_provider_takes_no_args(self) -> None:
        """No api_key required; that's the whole point of包 A."""
        provider = build_offline_provider()
        assert isinstance(provider, OfflineLLMProvider)
        assert provider.model_name == "offline-demo"


class TestEndToEndWithSuggestionEngine:
    """SuggestionEngine should treat the offline provider the same as anthropic/moonshot."""

    @pytest.mark.asyncio
    async def test_engine_produces_full_suggestion_offline(self) -> None:
        from datetime import date

        from src.alerts import scan_batch
        from src.repository import load_batches, load_customer_config
        from src.suggestion import SuggestionEngine

        config = load_customer_config("customerA")
        batches = load_batches("customerA")
        batch = next(b for b in batches if b.batch_id == "A-001")
        alert = scan_batch(batch, config.alert_thresholds, today=date(2026, 5, 26))
        assert alert is not None

        engine = SuggestionEngine(provider=OfflineLLMProvider())
        suggestion = await engine.suggest(batch, alert, config)

        assert suggestion.batch_id == "A-001"
        assert suggestion.customer_id == "customerA"
        assert suggestion.is_standard is True  # must be in enabled_actions
        assert suggestion.savings_estimate > 0
        assert suggestion.llm_model == "offline-demo"
