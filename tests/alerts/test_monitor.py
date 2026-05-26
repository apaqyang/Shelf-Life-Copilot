"""Tests for the monitoring engine — coverage of every threshold boundary."""

from __future__ import annotations

from datetime import date

import pytest

from src.alerts.monitor import (
    AlertThresholds,
    calculate_days_left,
    classify_severity,
    scan_batch,
)
from src.models import Batch, Severity


@pytest.fixture
def default_thresholds() -> AlertThresholds:
    return AlertThresholds()


def _make_batch(expiry_date: date) -> Batch:
    return Batch(
        batch_id="B-001",
        material_id="M-001",
        material_name="冷冻虾仁",
        production_date=date(2026, 3, 15),
        expiry_date=expiry_date,
        stock_qty=850.0,
        customer_id="customerA",
    )


class TestAlertThresholds:
    def test_default_thresholds(self) -> None:
        thresholds = AlertThresholds()
        assert thresholds.yellow == 30
        assert thresholds.orange == 15
        assert thresholds.red == 7

    def test_thresholds_must_be_strictly_ordered(self) -> None:
        with pytest.raises(ValueError, match="must satisfy"):
            AlertThresholds(yellow=10, orange=15, red=20)

    def test_equal_thresholds_rejected(self) -> None:
        with pytest.raises(ValueError):
            AlertThresholds(yellow=15, orange=15, red=7)


class TestCalculateDaysLeft:
    def test_future_expiry_returns_positive(self) -> None:
        assert (
            calculate_days_left(
                expiry_date=date(2026, 6, 14),
                today=date(2026, 5, 26),
            )
            == 19
        )

    def test_today_is_expiry_returns_zero(self) -> None:
        assert (
            calculate_days_left(
                expiry_date=date(2026, 5, 26),
                today=date(2026, 5, 26),
            )
            == 0
        )

    def test_already_expired_returns_negative(self) -> None:
        assert (
            calculate_days_left(
                expiry_date=date(2026, 5, 20),
                today=date(2026, 5, 26),
            )
            == -6
        )

    def test_defaults_to_today_when_not_provided(self) -> None:
        result = calculate_days_left(expiry_date=date.today())
        assert result == 0


class TestClassifySeverity:
    def test_above_yellow_returns_none(self, default_thresholds: AlertThresholds) -> None:
        assert classify_severity(31, default_thresholds) is Severity.NONE

    def test_at_yellow_boundary(self, default_thresholds: AlertThresholds) -> None:
        assert classify_severity(30, default_thresholds) is Severity.YELLOW

    def test_inside_yellow_range(self, default_thresholds: AlertThresholds) -> None:
        assert classify_severity(20, default_thresholds) is Severity.YELLOW

    def test_at_orange_boundary(self, default_thresholds: AlertThresholds) -> None:
        assert classify_severity(15, default_thresholds) is Severity.ORANGE

    def test_inside_orange_range(self, default_thresholds: AlertThresholds) -> None:
        assert classify_severity(10, default_thresholds) is Severity.ORANGE

    def test_at_red_boundary(self, default_thresholds: AlertThresholds) -> None:
        assert classify_severity(7, default_thresholds) is Severity.RED

    def test_expired_returns_red(self, default_thresholds: AlertThresholds) -> None:
        assert classify_severity(-3, default_thresholds) is Severity.RED


class TestScanBatch:
    def test_healthy_batch_yields_no_alert(self, default_thresholds: AlertThresholds) -> None:
        batch = _make_batch(expiry_date=date(2026, 12, 1))
        result = scan_batch(batch, default_thresholds, today=date(2026, 5, 26))
        assert result is None

    def test_yellow_batch_yields_yellow_alert(self, default_thresholds: AlertThresholds) -> None:
        batch = _make_batch(expiry_date=date(2026, 6, 14))
        alert = scan_batch(batch, default_thresholds, today=date(2026, 5, 26))
        assert alert is not None
        assert alert.severity is Severity.YELLOW
        assert alert.days_left == 19
        assert alert.batch_id == "B-001"
        assert alert.customer_id == "customerA"

    def test_red_batch_yields_red_alert(self, default_thresholds: AlertThresholds) -> None:
        batch = _make_batch(expiry_date=date(2026, 5, 30))
        alert = scan_batch(batch, default_thresholds, today=date(2026, 5, 26))
        assert alert is not None
        assert alert.severity is Severity.RED
        assert alert.days_left == 4
