"""WeCom webhook (路径 B server-side).

v0.1 ships the click-event router so a real Application's ✅ 同意 / ❌ 稍后 /
💬 改方案 button can land in the audit log, plus a `WebhookCrypto` seam whose
v0.1 default (`PlaintextCrypto`) does no AES / signature check. Real AES
decryption + signature verification land in the enterprise `wecom_realtime`
plugin, which swaps itself in via `set_webhook_crypto`.
"""

from src.webhook.crypto import (
    PlaintextCrypto,
    WebhookCrypto,
    get_webhook_crypto,
    reset_webhook_crypto,
    set_webhook_crypto,
)
from src.webhook.router import router

__all__ = [
    "PlaintextCrypto",
    "WebhookCrypto",
    "get_webhook_crypto",
    "reset_webhook_crypto",
    "router",
    "set_webhook_crypto",
]
