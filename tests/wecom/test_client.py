"""Tests for the WecomClient Protocol and DryRunWecomClient."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from src.models import Card, CardButton, CardKind
from src.wecom.client import (
    DryRunWecomClient,
    WebhookWecomClient,
    WecomClient,
    WecomPushError,
)


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


_WEBHOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=FAKE-KEY-FOR-TESTS"


def _ok_handler(seen: list[dict[str, object]]) -> object:
    """MockTransport handler that records requests and returns errcode=0."""

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "method": request.method,
                "url": str(request.url),
                "body": json.loads(request.content.decode("utf-8")),
            }
        )
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

    return _handler


class TestWebhookWecomClient:
    """Group-bot webhook path — verified against the documented JSON shape.

    We never hit the real WeCom endpoint in tests; httpx.MockTransport intercepts
    every request so we can assert URL / body / error handling deterministically.
    """

    async def test_send_card_posts_markdown_payload_to_webhook(self, card: Card) -> None:
        seen: list[dict[str, object]] = []
        http = httpx.AsyncClient(transport=httpx.MockTransport(_ok_handler(seen)))
        client = WebhookWecomClient(_WEBHOOK_URL, http_client=http)

        await client.send_card(card)

        assert len(seen) == 1
        assert seen[0]["method"] == "POST"
        assert seen[0]["url"] == _WEBHOOK_URL
        assert seen[0]["body"] == {
            "msgtype": "markdown",
            "markdown": {"content": card.markdown},
        }

    async def test_implements_protocol(self) -> None:
        client: WecomClient = WebhookWecomClient(_WEBHOOK_URL)
        assert hasattr(client, "send_card")

    async def test_errcode_nonzero_raises_with_errmsg(self, card: Card) -> None:
        def _handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"errcode": 93000, "errmsg": "invalid webhook url"})

        http = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        client = WebhookWecomClient(_WEBHOOK_URL, http_client=http)

        with pytest.raises(WecomPushError, match="93000"):
            await client.send_card(card)

    async def test_http_4xx_raises(self, card: Card) -> None:
        def _handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="not found")

        http = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        client = WebhookWecomClient(_WEBHOOK_URL, http_client=http)

        with pytest.raises(WecomPushError, match="404"):
            await client.send_card(card)

    async def test_network_error_wrapped(self, card: Card) -> None:
        def _handler(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("dns failure")

        http = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        client = WebhookWecomClient(_WEBHOOK_URL, http_client=http)

        with pytest.raises(WecomPushError, match="dns failure"):
            await client.send_card(card)

    async def test_multiple_sends_share_client(self, card: Card) -> None:
        """Reusing one client across sends must not raise (no double-close)."""
        seen: list[dict[str, object]] = []
        http = httpx.AsyncClient(transport=httpx.MockTransport(_ok_handler(seen)))
        client = WebhookWecomClient(_WEBHOOK_URL, http_client=http)

        await client.send_card(card)
        await client.send_card(card.model_copy(update={"batch_id": "A-002"}))

        assert len(seen) == 2
        assert seen[1]["body"]["markdown"]["content"] == card.markdown  # markdown unchanged

    async def test_send_card_logs_at_info_level(
        self, card: Card, caplog: pytest.LogCaptureFixture
    ) -> None:
        seen: list[dict[str, object]] = []
        http = httpx.AsyncClient(transport=httpx.MockTransport(_ok_handler(seen)))
        client = WebhookWecomClient(_WEBHOOK_URL, http_client=http)
        caplog.set_level(logging.INFO, logger="src.wecom.client")

        await client.send_card(card)

        assert any("A-001" in r.message for r in caplog.records)

    async def test_default_http_client_self_constructed(
        self, card: Card, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When no http_client is injected, send_card must build its own httpx.AsyncClient."""
        seen: list[dict[str, object]] = []
        # Capture the real class up front before we monkeypatch the module reference.
        real_async_client = httpx.AsyncClient

        def _factory(*_args: object, **_kw: object) -> httpx.AsyncClient:
            return real_async_client(transport=httpx.MockTransport(_ok_handler(seen)))

        from src.wecom import client as wecom_client_module

        monkeypatch.setattr(wecom_client_module.httpx, "AsyncClient", _factory)
        client = WebhookWecomClient(_WEBHOOK_URL)  # no http_client → goes through default path

        await client.send_card(card)
        assert len(seen) == 1
        assert seen[0]["url"] == _WEBHOOK_URL

    async def test_non_json_response_raises(self, card: Card) -> None:
        def _handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>not json</html>")

        http = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        client = WebhookWecomClient(_WEBHOOK_URL, http_client=http)

        with pytest.raises(WecomPushError, match="non-JSON"):
            await client.send_card(card)
