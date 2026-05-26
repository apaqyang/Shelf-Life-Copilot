"""Tests for CustomerConfig — including parsing rules and invariants."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from src.alerts.monitor import AlertThresholds
from src.models import ActionType, CustomerConfig


def _base_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "customer_id": "customerA",
        "industry": "frozen_seafood",
        "enabled_actions": ["transform", "discount_clearance"],
        "disabled_actions": ["employee_canteen"],
        "industry_phrases": {"transform": "转加工为下游产品"},
        "alert_thresholds": {"yellow": 30, "orange": 15, "red": 7},
        "decision_makers": ["userid_1"],
    }
    payload.update(overrides)
    return payload


class TestCustomerConfigParsing:
    def test_parses_minimum_payload(self) -> None:
        config = CustomerConfig.model_validate(_base_payload())
        assert config.customer_id == "customerA"
        assert ActionType.TRANSFORM in config.enabled_actions
        assert config.alert_thresholds == AlertThresholds(yellow=30, orange=15, red=7)

    def test_industry_phrases_keys_coerce_to_action_type(self) -> None:
        config = CustomerConfig.model_validate(_base_payload())
        assert config.industry_phrases[ActionType.TRANSFORM] == "转加工为下游产品"

    def test_disabled_actions_default_empty(self) -> None:
        payload = _base_payload()
        del payload["disabled_actions"]
        config = CustomerConfig.model_validate(payload)
        assert config.disabled_actions == []


class TestCustomerConfigInvariants:
    def test_overlapping_enabled_and_disabled_rejected(self) -> None:
        payload = _base_payload(
            enabled_actions=["transform", "discount_clearance"],
            disabled_actions=["transform"],
        )
        with pytest.raises(ValidationError, match="both enabled and disabled"):
            CustomerConfig.model_validate(payload)

    def test_empty_enabled_actions_rejected(self) -> None:
        payload = _base_payload(enabled_actions=[])
        with pytest.raises(ValidationError, match="must not be empty"):
            CustomerConfig.model_validate(payload)

    def test_invalid_thresholds_propagate_as_validation_error(self) -> None:
        payload = _base_payload(alert_thresholds={"yellow": 10, "orange": 15, "red": 20})
        with pytest.raises(ValidationError):
            CustomerConfig.model_validate(payload)

    def test_alert_thresholds_accepts_already_constructed_object(self) -> None:
        payload = _base_payload(alert_thresholds=AlertThresholds(yellow=20, orange=10, red=3))
        config = CustomerConfig.model_validate(payload)
        assert config.alert_thresholds.yellow == 20

    def test_alert_thresholds_rejects_wrong_type(self) -> None:
        payload = _base_payload(alert_thresholds="not_a_dict")
        with pytest.raises(TypeError, match="must be a dict or AlertThresholds"):
            CustomerConfig.model_validate(payload)


class TestCustomerConfigAvgSavings:
    def test_default_avg_savings_when_not_provided(self) -> None:
        config = CustomerConfig.model_validate(_base_payload())
        assert config.avg_savings_per_batch == 5000.0

    def test_custom_avg_savings_accepted(self) -> None:
        config = CustomerConfig.model_validate(_base_payload(avg_savings_per_batch=8333.0))
        assert config.avg_savings_per_batch == 8333.0

    def test_zero_avg_savings_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CustomerConfig.model_validate(_base_payload(avg_savings_per_batch=0))

    def test_negative_avg_savings_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CustomerConfig.model_validate(_base_payload(avg_savings_per_batch=-100))


class TestCustomerConfigImmutability:
    def test_model_is_frozen(self) -> None:
        config = CustomerConfig.model_validate(_base_payload())
        with pytest.raises(ValidationError):
            config.customer_id = "customerB"  # type: ignore[misc]
