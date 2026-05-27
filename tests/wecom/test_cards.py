"""Tests for the 4 WeCom card templates.

The renderers are pure functions: same inputs always produce the same markdown.
We assert on (a) Card metadata and (b) substring presence in markdown — never on
exact full-text equality, so phrasing tweaks don't churn the test suite.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.models import (
    ActionType,
    Alert,
    AlertThresholds,
    Batch,
    CardKind,
    CustomerConfig,
    Severity,
    Suggestion,
)
from src.wecom.cards import (
    render_alert_card,
    render_card_for_alert,
    render_out_of_scope_card,
    render_receipt_card,
    render_work_order_card,
)


@pytest.fixture
def customer() -> CustomerConfig:
    return CustomerConfig(
        customer_id="customerA",
        industry="frozen_seafood",
        enabled_actions=[
            ActionType.TRANSFORM,
            ActionType.DISCOUNT_CLEARANCE,
            ActionType.TRANSFER_WAREHOUSE,
            ActionType.REPORT_LOSS,
        ],
        disabled_actions=[ActionType.EMPLOYEE_CANTEEN],
        industry_phrases={
            ActionType.TRANSFORM: "转加工为虾饺馅 / 鱼丸 等下游产品",
            ActionType.DISCOUNT_CLEARANCE: "打折清仓至 B2B 渠道",
        },
        alert_thresholds=AlertThresholds(yellow=30, orange=15, red=7),
        decision_makers=["wecom_userid_zhangzong"],
        avg_savings_per_batch=8333.0,
    )


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
        severity=Severity.ORANGE,
        days_left=14,
    )


@pytest.fixture
def standard_suggestion() -> Suggestion:
    return Suggestion(
        batch_id="A-001",
        customer_id="customerA",
        action=ActionType.TRANSFORM,
        savings_estimate=8500.0,
        rationale="历史采纳率高，可消化全部库存。",
        confidence=0.85,
        is_standard=True,
        llm_model="claude-sonnet-4-6",
    )


@pytest.fixture
def out_of_scope_suggestion() -> Suggestion:
    return Suggestion(
        batch_id="A-001",
        customer_id="customerA",
        action=ActionType.EMPLOYEE_CANTEEN,  # disabled for customerA
        savings_estimate=2000.0,
        rationale="转员工食堂当样品消化。",
        confidence=0.60,
        is_standard=False,
        llm_model="claude-haiku-4-5",
        user_feedback="送给客户当样品",
    )


class TestRenderAlertCard:
    def test_kind_and_identifiers(
        self, batch: Batch, alert: Alert, standard_suggestion: Suggestion, customer: CustomerConfig
    ) -> None:
        card = render_alert_card(batch, alert, standard_suggestion, customer)
        assert card.kind is CardKind.ALERT
        assert card.batch_id == "A-001"
        assert card.customer_id == "customerA"
        assert card.is_standard is True

    def test_markdown_contains_key_facts(
        self, batch: Batch, alert: Alert, standard_suggestion: Suggestion, customer: CustomerConfig
    ) -> None:
        card = render_alert_card(batch, alert, standard_suggestion, customer)
        md = card.markdown
        assert "冷冻虾仁" in md
        assert "A-001" in md
        assert "2026-06-14" in md
        assert "850" in md  # stock qty
        assert "14" in md  # days_left
        assert "8,500" in md or "8500" in md
        assert "85%" in md
        assert "历史采纳率高" in md
        # phrase from industry_phrases (not the raw enum value)
        assert "转加工为虾饺馅" in md
        assert "transform" not in md  # raw enum should not leak

    def test_three_decision_buttons(
        self, batch: Batch, alert: Alert, standard_suggestion: Suggestion, customer: CustomerConfig
    ) -> None:
        card = render_alert_card(batch, alert, standard_suggestion, customer)
        action_keys = [b.action_key for b in card.buttons]
        assert action_keys == ["approve", "snooze", "revise"]

    def test_mentions_decision_makers(
        self, batch: Batch, alert: Alert, standard_suggestion: Suggestion, customer: CustomerConfig
    ) -> None:
        card = render_alert_card(batch, alert, standard_suggestion, customer)
        assert card.mentioned_userids == ["wecom_userid_zhangzong"]

    def test_severity_label_present(
        self, batch: Batch, alert: Alert, standard_suggestion: Suggestion, customer: CustomerConfig
    ) -> None:
        card = render_alert_card(batch, alert, standard_suggestion, customer)
        assert "ORANGE" in card.markdown or "橙" in card.markdown

    def test_action_without_industry_phrase_falls_back_to_enum_label(
        self, batch: Batch, alert: Alert, customer: CustomerConfig
    ) -> None:
        # report_loss is enabled but no industry_phrase in fixture → fallback to a label
        suggestion = Suggestion(
            batch_id="A-001",
            customer_id="customerA",
            action=ActionType.REPORT_LOSS,
            savings_estimate=0.0,
            rationale="所有动作均不适用。",
            confidence=0.95,
            is_standard=True,
            llm_model="claude-sonnet-4-6",
        )
        card = render_alert_card(batch, alert, suggestion, customer)
        # Fallback uses a Chinese label, never the raw enum value.
        assert "report_loss" not in card.markdown
        assert "报损" in card.markdown


class TestRenderOutOfScopeCard:
    def test_kind_and_red_banner(
        self,
        batch: Batch,
        alert: Alert,
        out_of_scope_suggestion: Suggestion,
        customer: CustomerConfig,
    ) -> None:
        card = render_out_of_scope_card(batch, alert, out_of_scope_suggestion, customer)
        assert card.kind is CardKind.OUT_OF_SCOPE
        assert card.is_standard is False
        assert "非标准动作" in card.markdown
        assert "人工复核" in card.markdown

    def test_user_feedback_present_when_provided(
        self,
        batch: Batch,
        alert: Alert,
        out_of_scope_suggestion: Suggestion,
        customer: CustomerConfig,
    ) -> None:
        card = render_out_of_scope_card(batch, alert, out_of_scope_suggestion, customer)
        assert "送给客户当样品" in card.markdown

    def test_user_feedback_omitted_when_absent(
        self, batch: Batch, alert: Alert, customer: CustomerConfig
    ) -> None:
        suggestion = Suggestion(
            batch_id="A-001",
            customer_id="customerA",
            action=ActionType.EMPLOYEE_CANTEEN,
            savings_estimate=2000.0,
            rationale="员工内部消化。",
            confidence=0.7,
            is_standard=False,
            llm_model="claude-haiku-4-5",
            user_feedback=None,
        )
        card = render_out_of_scope_card(batch, alert, suggestion, customer)
        assert "用户反馈" not in card.markdown


class TestRenderCardForAlert:
    """The dispatcher picks alert vs out-of-scope based on suggestion.is_standard."""

    def test_standard_suggestion_routes_to_alert(
        self, batch: Batch, alert: Alert, standard_suggestion: Suggestion, customer: CustomerConfig
    ) -> None:
        card = render_card_for_alert(batch, alert, standard_suggestion, customer)
        assert card.kind is CardKind.ALERT

    def test_out_of_scope_suggestion_routes_to_red_banner(
        self,
        batch: Batch,
        alert: Alert,
        out_of_scope_suggestion: Suggestion,
        customer: CustomerConfig,
    ) -> None:
        card = render_card_for_alert(batch, alert, out_of_scope_suggestion, customer)
        assert card.kind is CardKind.OUT_OF_SCOPE


class TestRenderWorkOrderCard:
    def test_kind_and_mentions(self, batch: Batch, standard_suggestion: Suggestion) -> None:
        card = render_work_order_card(
            batch,
            standard_suggestion,
            foreman_userids=["wecom_userid_workshop_lead"],
            due_date=date(2026, 5, 29),
        )
        assert card.kind is CardKind.WORK_ORDER
        assert card.mentioned_userids == ["wecom_userid_workshop_lead"]

    def test_markdown_contains_action_and_due_date(
        self, batch: Batch, standard_suggestion: Suggestion
    ) -> None:
        card = render_work_order_card(
            batch,
            standard_suggestion,
            foreman_userids=["wecom_userid_workshop_lead"],
            due_date=date(2026, 5, 29),
        )
        md = card.markdown
        assert "工单" in md
        assert "A-001" in md
        assert "850" in md
        assert "2026-05-29" in md
        assert "已完成" in md  # completion button label

    def test_has_completion_button(self, batch: Batch, standard_suggestion: Suggestion) -> None:
        card = render_work_order_card(
            batch,
            standard_suggestion,
            foreman_userids=["wecom_userid_workshop_lead"],
            due_date=date(2026, 5, 29),
        )
        action_keys = [b.action_key for b in card.buttons]
        assert action_keys == ["complete"]


class TestRenderReceiptCard:
    def test_kind_and_no_buttons(self, batch: Batch, standard_suggestion: Suggestion) -> None:
        card = render_receipt_card(batch, standard_suggestion, actual_qty=840.0)
        assert card.kind is CardKind.RECEIPT
        assert card.buttons == []

    def test_markdown_contains_actual_qty_and_savings(
        self, batch: Batch, standard_suggestion: Suggestion
    ) -> None:
        card = render_receipt_card(batch, standard_suggestion, actual_qty=840.0)
        md = card.markdown
        assert "840" in md
        assert "8,500" in md or "8500" in md
        assert "完成" in md or "回执" in md
