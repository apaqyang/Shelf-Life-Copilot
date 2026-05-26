"""Tests for Batch and Severity models."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from src.models import Batch, Severity


class TestSeverity:
    def test_severity_string_values(self) -> None:
        assert Severity.NONE.value == "none"
        assert Severity.YELLOW.value == "yellow"
        assert Severity.ORANGE.value == "orange"
        assert Severity.RED.value == "red"


class TestBatch:
    def test_minimal_batch_creation_applies_defaults(self) -> None:
        batch = Batch(
            batch_id="B-001",
            material_id="M-001",
            material_name="冷冻虾仁",
            production_date=date(2026, 3, 15),
            expiry_date=date(2026, 6, 14),
            stock_qty=850.0,
            customer_id="customerA",
        )
        assert batch.batch_id == "B-001"
        assert batch.unit == "kg"
        assert batch.warehouse == "default"

    def test_negative_stock_qty_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Batch(
                batch_id="B-001",
                material_id="M-001",
                material_name="冷冻虾仁",
                production_date=date(2026, 3, 15),
                expiry_date=date(2026, 6, 14),
                stock_qty=-1.0,
                customer_id="customerA",
            )

    def test_zero_stock_qty_is_allowed(self) -> None:
        batch = Batch(
            batch_id="B-001",
            material_id="M-001",
            material_name="冷冻虾仁",
            production_date=date(2026, 3, 15),
            expiry_date=date(2026, 6, 14),
            stock_qty=0.0,
            customer_id="customerA",
        )
        assert batch.stock_qty == 0.0
