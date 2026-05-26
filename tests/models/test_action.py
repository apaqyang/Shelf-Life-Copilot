"""Tests for the ActionType enum."""

from __future__ import annotations

from src.models import ActionType


class TestActionType:
    def test_action_type_values(self) -> None:
        assert ActionType.TRANSFORM.value == "transform"
        assert ActionType.DISCOUNT_CLEARANCE.value == "discount_clearance"
        assert ActionType.EMPLOYEE_CANTEEN.value == "employee_canteen"
        assert ActionType.TRANSFER_WAREHOUSE.value == "transfer_warehouse"
        assert ActionType.REPORT_LOSS.value == "report_loss"

    def test_action_type_is_string_subclass(self) -> None:
        assert isinstance(ActionType.TRANSFORM, str)
        assert ActionType.TRANSFORM == "transform"

    def test_action_type_count(self) -> None:
        assert len(list(ActionType)) == 5
