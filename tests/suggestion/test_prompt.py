"""Tests for prompt construction — pure-function unit tests, no LLM calls."""

from __future__ import annotations

from datetime import date

import pytest

from src.models import ActionType, Alert, AlertThresholds, Batch, CustomerConfig, Severity
from src.suggestion.prompt import SYSTEM_PROMPT, build_user_prompt, format_actions_block


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
        enabled_actions=[ActionType.TRANSFORM, ActionType.DISCOUNT_CLEARANCE],
        industry_phrases={
            ActionType.TRANSFORM: "转加工为虾饺馅",
            ActionType.DISCOUNT_CLEARANCE: "打折清仓至 B2B 渠道",
        },
        alert_thresholds=AlertThresholds(),
        decision_makers=["userid_1"],
        avg_savings_per_batch=5000.0,
    )


class TestFormatActionsBlock:
    def test_lists_each_enabled_action(self) -> None:
        block = format_actions_block(
            [ActionType.TRANSFORM, ActionType.DISCOUNT_CLEARANCE],
            {ActionType.TRANSFORM: "转加工为虾饺馅"},
        )
        assert "transform: 转加工为虾饺馅" in block
        assert "discount_clearance" in block

    def test_falls_back_to_action_value_when_phrase_missing(self) -> None:
        block = format_actions_block([ActionType.REPORT_LOSS], {})
        assert "report_loss: report_loss" in block


class TestSystemPrompt:
    def test_mentions_tool_name(self) -> None:
        assert "submit_suggestion" in SYSTEM_PROMPT

    def test_specifies_chinese_rationale_constraint(self) -> None:
        assert "50 字" in SYSTEM_PROMPT


class TestBuildUserPrompt:
    def test_contains_batch_context(
        self, batch: Batch, alert: Alert, customer: CustomerConfig
    ) -> None:
        prompt = build_user_prompt(batch, alert, customer)
        assert "冷冻虾仁" in prompt
        assert "A-001" in prompt
        assert "19 天" in prompt
        assert "yellow" in prompt

    def test_contains_enabled_actions(
        self, batch: Batch, alert: Alert, customer: CustomerConfig
    ) -> None:
        prompt = build_user_prompt(batch, alert, customer)
        assert "transform" in prompt
        assert "discount_clearance" in prompt

    def test_uses_customer_avg_savings_with_thousands_separator(
        self, batch: Batch, alert: Alert
    ) -> None:
        customer = CustomerConfig(
            customer_id="customerA",
            industry="frozen_seafood",
            enabled_actions=[ActionType.TRANSFORM],
            alert_thresholds=AlertThresholds(),
            decision_makers=["userid_1"],
            avg_savings_per_batch=8500.0,
        )
        prompt = build_user_prompt(batch, alert, customer)
        assert "¥8,500" in prompt

    def test_no_feedback_section_when_feedback_none(
        self, batch: Batch, alert: Alert, customer: CustomerConfig
    ) -> None:
        prompt = build_user_prompt(batch, alert, customer)
        assert "用户反馈" not in prompt

    def test_feedback_section_added_when_feedback_present(
        self, batch: Batch, alert: Alert, customer: CustomerConfig
    ) -> None:
        prompt = build_user_prompt(
            batch,
            alert,
            customer,
            feedback="虾饺线满了，改成打折清仓",
        )
        assert "用户反馈" in prompt
        assert "虾饺线满了" in prompt
        # Out-of-scope routing instruction must be explicit.
        assert "用户特别要求" in prompt or "非标准动作" in prompt


class TestSystemPromptOutOfScopeRule:
    def test_system_prompt_describes_disabled_action_override(self) -> None:
        # PRD §5.3: the LLM is allowed to pick disabled actions only when the user
        # explicitly asks. The system prompt must say so.
        assert "用户特别要求" in SYSTEM_PROMPT
        assert "非标准" in SYSTEM_PROMPT
