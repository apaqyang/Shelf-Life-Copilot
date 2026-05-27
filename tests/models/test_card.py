"""Tests for the Card model — value object representing a WeCom card payload."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from src.models.card import Card, CardButton, CardKind


def _base_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": CardKind.ALERT,
        "customer_id": "customerA",
        "batch_id": "A-001",
        "title": "【临期预警】2026-05-26 07:00",
        "markdown": "## 冷冻虾仁\n剩余 19 天",
        "buttons": [
            CardButton(label="✅ 同意", action_key="approve"),
            CardButton(label="💬 改方案", action_key="revise"),
        ],
    }
    payload.update(overrides)
    return payload


class TestCardCreation:
    def test_minimal_creation_succeeds(self) -> None:
        card = Card(**_base_payload())
        assert card.kind is CardKind.ALERT
        assert card.is_standard is True
        assert card.mentioned_userids == []

    def test_out_of_scope_card_defaults_is_standard_false(self) -> None:
        card = Card(**_base_payload(kind=CardKind.OUT_OF_SCOPE, is_standard=False))
        assert card.is_standard is False

    def test_work_order_card_can_mention(self) -> None:
        card = Card(
            **_base_payload(
                kind=CardKind.WORK_ORDER,
                mentioned_userids=["wecom_userid_zhangzong"],
            )
        )
        assert card.mentioned_userids == ["wecom_userid_zhangzong"]


class TestCardValidation:
    def test_empty_title_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Card(**_base_payload(title=""))

    def test_empty_markdown_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Card(**_base_payload(markdown=""))


class TestCardButton:
    def test_button_creation(self) -> None:
        button = CardButton(label="✅ 同意", action_key="approve")
        assert button.label == "✅ 同意"
        assert button.action_key == "approve"

    def test_empty_label_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CardButton(label="", action_key="approve")

    def test_empty_action_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CardButton(label="✅ 同意", action_key="")

    def test_button_is_frozen(self) -> None:
        button = CardButton(label="✅ 同意", action_key="approve")
        with pytest.raises(ValidationError):
            button.label = "其他"  # type: ignore[misc]


class TestCardImmutability:
    def test_model_is_frozen(self) -> None:
        card = Card(**_base_payload())
        with pytest.raises(ValidationError):
            card.title = "其他"  # type: ignore[misc]
