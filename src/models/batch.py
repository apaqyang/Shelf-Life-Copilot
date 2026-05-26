"""Batch and severity data models."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, NonNegativeFloat


class Severity(StrEnum):
    """Alert severity. Order from safe to urgent: NONE → YELLOW → ORANGE → RED."""

    NONE = "none"
    YELLOW = "yellow"
    ORANGE = "orange"
    RED = "red"


class Batch(BaseModel):
    """A physical inventory batch with a known expiry date."""

    batch_id: str
    material_id: str
    material_name: str
    production_date: date
    expiry_date: date
    stock_qty: NonNegativeFloat
    unit: str = Field(default="kg")
    warehouse: str = Field(default="default")
    customer_id: str
