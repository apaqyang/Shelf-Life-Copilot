"""WeCom callback crypto seam — Open Core boundary for AES + signature check.

v0.1 ships `PlaintextCrypto`: the URL-verification handshake echoes `echostr`
verbatim and no signature is checked. That is only safe behind a private
network / VPN, which matches v0.1 self-testing.

The enterprise `wecom_realtime` plugin implements this same `WebhookCrypto`
protocol (AES-256-CBC decrypt + msg_signature verification per WeCom's spec)
and installs itself via `set_webhook_crypto`, making the public endpoint
production-safe without touching the open-source router.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class WebhookCrypto(Protocol):
    """Decrypts the WeCom URL-verification handshake and event bodies."""

    def verify_url(self, echostr: str) -> str: ...  # pragma: no cover

    def decrypt(self, ciphertext: str) -> str: ...  # pragma: no cover


class PlaintextCrypto:
    """No-op crypto — echoes `echostr`, returns ciphertext unchanged."""

    def verify_url(self, echostr: str) -> str:
        return echostr

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext


_active_crypto: WebhookCrypto | None = None


def get_webhook_crypto() -> WebhookCrypto:
    """Return the active crypto — PlaintextCrypto unless a plugin overrode it."""
    global _active_crypto
    if _active_crypto is None:
        _active_crypto = PlaintextCrypto()
    return _active_crypto


def set_webhook_crypto(crypto: WebhookCrypto) -> None:
    """Install a crypto implementation (the AES enterprise plugin calls this)."""
    global _active_crypto
    _active_crypto = crypto


def reset_webhook_crypto() -> None:
    """Drop back to PlaintextCrypto — primarily for tests."""
    global _active_crypto
    _active_crypto = None
