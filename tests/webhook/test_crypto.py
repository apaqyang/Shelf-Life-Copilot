"""Tests for the WebhookCrypto seam — Open Core boundary for AES + signature.

PlaintextCrypto is the v0.1 default (echo / passthrough); the enterprise
wecom_realtime plugin swaps in real AES via set_webhook_crypto.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from src.webhook import (
    PlaintextCrypto,
    WebhookCrypto,
    get_webhook_crypto,
    reset_webhook_crypto,
    set_webhook_crypto,
)


@pytest.fixture(autouse=True)
def _reset_active_crypto() -> Iterator[None]:
    reset_webhook_crypto()
    yield
    reset_webhook_crypto()


class TestPlaintextCrypto:
    def test_satisfies_protocol(self) -> None:
        assert isinstance(PlaintextCrypto(), WebhookCrypto)

    def test_verify_url_echoes(self) -> None:
        assert PlaintextCrypto().verify_url("hello") == "hello"

    def test_decrypt_is_passthrough(self) -> None:
        assert PlaintextCrypto().decrypt("{}") == "{}"


class TestActiveCryptoSeam:
    def test_default_is_plaintext(self) -> None:
        assert isinstance(get_webhook_crypto(), PlaintextCrypto)

    def test_set_overrides(self) -> None:
        class FakeAesCrypto:
            def verify_url(self, echostr: str) -> str:
                return "decrypted:" + echostr

            def decrypt(self, ciphertext: str) -> str:
                return "plain:" + ciphertext

        fake = FakeAesCrypto()
        assert isinstance(fake, WebhookCrypto)
        set_webhook_crypto(fake)
        assert get_webhook_crypto() is fake

    def test_reset_restores_default(self) -> None:
        set_webhook_crypto(PlaintextCrypto())
        reset_webhook_crypto()
        assert isinstance(get_webhook_crypto(), PlaintextCrypto)
