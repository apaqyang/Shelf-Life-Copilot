"""Verified work-order outcome quality reporting and regression gates."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from src.models import ActionType, Decision, Suggestion


class OutcomeObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    action: ActionType
    estimated_savings: float = Field(ge=0)
    actual_savings: float = Field(ge=0)


class QualitySegment(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    action: ActionType
    sample_count: int = Field(ge=1)
    mean_estimated_savings: float = Field(ge=0)
    mean_actual_savings: float = Field(ge=0)
    mean_bias: float
    mean_absolute_error: float = Field(ge=0)
    normalized_absolute_error: float = Field(ge=0)


class OutcomeQualityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    customer_id: str
    verified_count: int = Field(ge=0)
    unmatched_count: int = Field(ge=0)
    segments: list[QualitySegment]
    gate_passed: bool
    gate_reasons: list[str]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def build_outcome_quality_report(
    *,
    customer_id: str,
    decisions: list[Decision],
    suggestion_for_batch: Callable[[str, str, datetime], Suggestion | None],
    min_verified_samples: int = 5,
    max_normalized_error: float = 0.5,
) -> OutcomeQualityReport:
    if min_verified_samples <= 0 or max_normalized_error < 0:
        raise ValueError("invalid quality gate configuration")
    observations: list[OutcomeObservation] = []
    unmatched = 0
    for decision in decisions:
        if decision.customer_id != customer_id or decision.actual_savings is None:
            continue
        suggestion = suggestion_for_batch(customer_id, decision.batch_id, decision.decided_at)
        if suggestion is None:
            unmatched += 1
            continue
        observations.append(
            OutcomeObservation(
                provider=suggestion.llm_model,
                action=decision.action,
                estimated_savings=decision.savings_estimate,
                actual_savings=decision.actual_savings,
            )
        )

    grouped: dict[tuple[str, ActionType], list[OutcomeObservation]] = defaultdict(list)
    for observation in observations:
        grouped[(observation.provider, observation.action)].append(observation)
    segments = [
        _segment(provider, action, values)
        for (provider, action), values in sorted(grouped.items(), key=lambda item: item[0])
    ]
    reasons: list[str] = []
    if len(observations) < min_verified_samples:
        reasons.append(f"verified samples {len(observations)} below minimum {min_verified_samples}")
    failing = [
        f"{segment.provider}/{segment.action.value}"
        for segment in segments
        if segment.normalized_absolute_error > max_normalized_error
    ]
    if failing:
        reasons.append("normalized error exceeds threshold: " + ", ".join(failing))
    return OutcomeQualityReport(
        customer_id=customer_id,
        verified_count=len(observations),
        unmatched_count=unmatched,
        segments=segments,
        gate_passed=not reasons,
        gate_reasons=reasons,
    )


def _segment(
    provider: str,
    action: ActionType,
    observations: list[OutcomeObservation],
) -> QualitySegment:
    count = len(observations)
    estimated = sum(item.estimated_savings for item in observations)
    actual = sum(item.actual_savings for item in observations)
    absolute_error = sum(abs(item.estimated_savings - item.actual_savings) for item in observations)
    denominator = sum(max(item.actual_savings, 1.0) for item in observations)
    return QualitySegment(
        provider=provider,
        action=action,
        sample_count=count,
        mean_estimated_savings=estimated / count,
        mean_actual_savings=actual / count,
        mean_bias=(estimated - actual) / count,
        mean_absolute_error=absolute_error / count,
        normalized_absolute_error=absolute_error / denominator,
    )
