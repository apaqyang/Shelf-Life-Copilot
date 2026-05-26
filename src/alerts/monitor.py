"""Monitoring engine — calculates days_left and classifies severity."""

from __future__ import annotations

from datetime import date

from src.models.alert import Alert
from src.models.batch import Batch, Severity
from src.models.thresholds import AlertThresholds


def calculate_days_left(expiry_date: date, today: date | None = None) -> int:
    """Days between today and expiry_date. Negative means already expired."""
    reference = today if today is not None else date.today()
    return (expiry_date - reference).days


def classify_severity(days_left: int, thresholds: AlertThresholds) -> Severity:
    """Classify a days_left value against the configured thresholds."""
    if days_left <= thresholds.red:
        return Severity.RED
    if days_left <= thresholds.orange:
        return Severity.ORANGE
    if days_left <= thresholds.yellow:
        return Severity.YELLOW
    return Severity.NONE


def scan_batch(
    batch: Batch,
    thresholds: AlertThresholds,
    today: date | None = None,
) -> Alert | None:
    """Scan one batch; emit an Alert if it crosses any threshold, else None."""
    days_left = calculate_days_left(batch.expiry_date, today=today)
    severity = classify_severity(days_left, thresholds)
    if severity is Severity.NONE:
        return None
    return Alert(
        batch_id=batch.batch_id,
        customer_id=batch.customer_id,
        severity=severity,
        days_left=days_left,
    )
