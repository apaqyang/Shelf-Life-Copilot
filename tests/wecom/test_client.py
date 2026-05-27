"""Tests for the WecomClient Protocol and DryRunWecomClient."""

from __future__ import annotations

import logging

import pytest

from src.models import Card, CardButton, CardKind
from src.wecom.client import DryRunWecomClient, WecomClient


@pytest.fixture
def card() -> Card:
    return Card(
        kind=CardKind.ALERT,
        customer_id="customerA",
        batch_id="A-001",
        title="【临期预警】冷冻虾仁",
        markdown="## test card",
        buttons=[CardButton(label="✅ 同意", action_key="approve")],
        mentioned_userids=["wecom_userid_zhangzong"],
    )


class TestDryRunWecomClient:
    async def test_send_card_collects_payloads(self, card: Card) -> None:
        client = DryRunWecomClient()
        await client.send_card(card)
        assert client.sent == [card]

    async def test_multiple_cards_preserved_in_order(self, card: Card) -> None:
        client = DryRunWecomClient()
        other = card.model_copy(update={"batch_id": "A-002"})
        await client.send_card(card)
        await client.send_card(other)
        assert [c.batch_id for c in client.sent] == ["A-001", "A-002"]

    async def test_send_card_logs_at_info_level(
        self, card: Card, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO, logger="src.wecom.client")
        client = DryRunWecomClient()
        await client.send_card(card)
        assert any("A-001" in record.message for record in caplog.records)

    async def test_implements_protocol(self) -> None:
        """DryRunWecomClient must satisfy the WecomClient Protocol at runtime."""
        client: WecomClient = DryRunWecomClient()
        assert hasattr(client, "send_card")
