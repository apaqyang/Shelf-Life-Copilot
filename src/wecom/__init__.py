"""WeCom layer — card rendering + (future) push client.

v0.1 implements pure-function renderers for the 4 card templates (alert / work
order / receipt / out-of-scope) plus a dry-run client that collects payloads
for offline demo. Real WeCom API integration is gated on customer's admin
permission approval (see TODO.md "阻塞 & 风险").
"""

from src.wecom.cards import (
    render_alert_card,
    render_card_for_alert,
    render_out_of_scope_card,
    render_receipt_card,
    render_work_order_card,
)
from src.wecom.client import DryRunWecomClient, WecomClient

__all__ = [
    "DryRunWecomClient",
    "WecomClient",
    "render_alert_card",
    "render_card_for_alert",
    "render_out_of_scope_card",
    "render_receipt_card",
    "render_work_order_card",
]
