"""Per-customer configuration: enabled actions, thresholds, industry phrases."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models.action import ActionType
from src.models.thresholds import AlertThresholds


class CustomerConfig(BaseModel):
    """Customer-specific configuration loaded from `data/config/<id>.actions.json`."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    customer_id: str
    industry: str
    enabled_actions: list[ActionType]
    disabled_actions: list[ActionType] = Field(default_factory=list)
    industry_phrases: dict[ActionType, str] = Field(default_factory=dict)
    alert_thresholds: AlertThresholds
    decision_makers: list[str]
    avg_savings_per_batch: float = Field(default=5000.0, gt=0.0)

    @field_validator("alert_thresholds", mode="before")
    @classmethod
    def _coerce_thresholds(cls, value: Any) -> AlertThresholds:
        if isinstance(value, AlertThresholds):
            return value
        if isinstance(value, dict):
            return AlertThresholds(**value)
        raise TypeError(
            f"alert_thresholds must be a dict or AlertThresholds, got {type(value).__name__}"
        )

    @model_validator(mode="after")
    def _check_action_consistency(self) -> CustomerConfig:
        overlap = set(self.enabled_actions) & set(self.disabled_actions)
        if overlap:
            raise ValueError(
                f"Actions cannot be both enabled and disabled: {sorted(o.value for o in overlap)}"
            )
        if not self.enabled_actions:
            raise ValueError("enabled_actions must not be empty")
        return self
