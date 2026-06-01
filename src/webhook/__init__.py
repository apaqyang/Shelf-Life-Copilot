"""WeCom webhook (路径 B server-side).

v0.1 ships the click-event router so a real Application's ✅ 同意 / ❌ 稍后 /
💬 改方案 button can land in the audit log. WeCom AES encryption and signature
verification are out of v0.1 scope (need a real corp_secret to test against);
they'll land alongside the customer PoC kickoff.
"""

from src.webhook.router import router

__all__ = ["router"]
