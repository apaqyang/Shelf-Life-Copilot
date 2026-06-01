"""Unit tests for the webhook business layer.

Handlers are sync, take an injected DecisionStore, and don't touch FastAPI —
that separation lets us test them with a `:memory:` store and zero HTTP setup.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.models import ActionType, DecisionOutcome, Suggestion
from src.persistence import DecisionStore, SuggestionStore
from src.webhook.handlers import (
    UnknownActionError,
    UnknownBatchError,
    handle_click,
)
from src.webhook.schemas import WecomEvent


def _click(event_key: str) -> WecomEvent:
    return WecomEvent(
        to_user_name="ww_corp",
        from_user_name="user_zhang",
        create_time=1717200000,
        msg_type="event",
        event="click",
        event_key=event_key,
        content=None,
    )


class TestHandleClick:
    def test_approve_writes_decision_with_approved_outcome(self) -> None:
        store = DecisionStore(":memory:")
        detail = handle_click(_click("approve:customerA:A-001"), store)

        assert "Recorded" in detail
        results = store.list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2027, 1, 1, tzinfo=UTC),
        )
        assert len(results) == 1
        d = results[0]
        assert d.batch_id == "A-001"
        assert d.customer_id == "customerA"
        assert d.material_name == "冷冻虾仁"  # resolved from batches/customerA.json
        assert d.outcome is DecisionOutcome.APPROVED

    def test_snooze_writes_decision_with_snoozed_outcome(self) -> None:
        store = DecisionStore(":memory:")
        handle_click(_click("snooze:customerA:A-001"), store)

        results = store.list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2027, 1, 1, tzinfo=UTC),
        )
        assert results[0].outcome is DecisionOutcome.SNOOZED

    def test_revise_returns_prompt_without_writing_decision(self) -> None:
        store = DecisionStore(":memory:")
        detail = handle_click(_click("revise:customerA:A-001"), store)

        assert "改方案" in detail
        results = store.list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2027, 1, 1, tzinfo=UTC),
        )
        assert results == []

    def test_unknown_action_raises(self) -> None:
        store = DecisionStore(":memory:")
        with pytest.raises(UnknownActionError, match="bogus"):
            handle_click(_click("bogus:customerA:A-001"), store)

    def test_malformed_event_key_raises(self) -> None:
        store = DecisionStore(":memory:")
        with pytest.raises(UnknownActionError, match="action:customer_id:batch_id"):
            handle_click(_click("approve_only_one_part"), store)

    def test_missing_event_key_raises(self) -> None:
        store = DecisionStore(":memory:")
        event = WecomEvent(
            to_user_name="ww_corp",
            from_user_name="u",
            create_time=1,
            msg_type="event",
            event="click",
            event_key=None,
            content=None,
        )
        with pytest.raises(UnknownActionError, match="missing"):
            handle_click(event, store)

    def test_unknown_batch_raises(self) -> None:
        store = DecisionStore(":memory:")
        with pytest.raises(UnknownBatchError, match="A-DOES-NOT-EXIST"):
            handle_click(_click("approve:customerA:A-DOES-NOT-EXIST"), store)

    def test_unknown_customer_raises(self) -> None:
        store = DecisionStore(":memory:")
        # load_batches raises FileNotFoundError → handler wraps as UnknownBatchError
        with pytest.raises(UnknownBatchError, match="customerZ"):
            handle_click(_click("approve:customerZ:A-001"), store)


class TestHandleClickWithSuggestionStore:
    """When a SuggestionStore is injected and the batch has a latest suggestion,
    the Decision must carry that suggestion's action + savings_estimate instead
    of the TRANSFORM/0.0 placeholders.
    """

    def _make_persisted_suggestion(self) -> Suggestion:
        from datetime import UTC, datetime

        return Suggestion(
            batch_id="A-001",
            customer_id="customerA",
            action=ActionType.DISCOUNT_CLEARANCE,
            savings_estimate=6200.0,
            rationale="清仓渠道吸收率 75%",
            confidence=0.78,
            is_standard=True,
            generated_at=datetime(2026, 5, 26, 7, 5, tzinfo=UTC),
            llm_model="claude-sonnet-4-6",
        )

    def test_approve_uses_suggestion_action_and_savings(self) -> None:
        from datetime import UTC, datetime

        decisions = DecisionStore(":memory:")
        suggestions = SuggestionStore(":memory:")
        suggestions.save(self._make_persisted_suggestion())

        handle_click(
            _click("approve:customerA:A-001"),
            decisions,
            suggestion_store=suggestions,
        )

        rows = decisions.list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2027, 1, 1, tzinfo=UTC),
        )
        assert len(rows) == 1
        d = rows[0]
        assert d.action is ActionType.DISCOUNT_CLEARANCE
        assert d.savings_estimate == 6200.0

    def test_falls_back_to_placeholders_when_no_suggestion_found(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from datetime import UTC, datetime

        decisions = DecisionStore(":memory:")
        suggestions = SuggestionStore(":memory:")  # empty store

        import logging

        caplog.set_level(logging.WARNING, logger="src.webhook.handlers")
        handle_click(
            _click("approve:customerA:A-001"),
            decisions,
            suggestion_store=suggestions,
        )

        rows = decisions.list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2027, 1, 1, tzinfo=UTC),
        )
        # Placeholder Decision still lands so the audit log isn't lost.
        assert len(rows) == 1
        assert rows[0].savings_estimate == 0.0
        assert rows[0].action is ActionType.TRANSFORM
        assert any("no suggestion" in r.message.lower() for r in caplog.records)

    def test_no_store_keeps_placeholder_behavior(self) -> None:
        """Backward compat: omitting suggestion_store keeps v0.1 placeholder behavior."""
        from datetime import UTC, datetime

        decisions = DecisionStore(":memory:")
        handle_click(_click("approve:customerA:A-001"), decisions)
        rows = decisions.list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2027, 1, 1, tzinfo=UTC),
        )
        assert rows[0].savings_estimate == 0.0
        assert rows[0].action is ActionType.TRANSFORM

    def test_revise_does_not_consume_suggestion(self) -> None:
        """`revise` click is a UI prompt; it must not touch DecisionStore even
        when a SuggestionStore is wired up."""
        from datetime import UTC, datetime

        decisions = DecisionStore(":memory:")
        suggestions = SuggestionStore(":memory:")
        suggestions.save(self._make_persisted_suggestion())

        detail = handle_click(
            _click("revise:customerA:A-001"),
            decisions,
            suggestion_store=suggestions,
        )
        assert "改方案" in detail
        rows = decisions.list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2027, 1, 1, tzinfo=UTC),
        )
        assert rows == []
