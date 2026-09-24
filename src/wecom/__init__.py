"""WeCom layer — card rendering + push clients.

v0.1 implements pure-function renderers for the 4 card templates (alert / work
order / receipt / out-of-scope), a dry-run client for offline demos, and a
group-bot webhook client. Interactive application messages require an
enterprise callback plugin and customer administrator approval.
"""

from src.wecom.cards import (
    render_alert_card,
    render_card_for_alert,
    render_monthly_summary_card,
    render_out_of_scope_card,
    render_receipt_card,
    render_work_order_card,
)
from src.wecom.client import DryRunWecomClient, WebhookWecomClient, WecomClient, WecomPushError

__all__ = [
    "DryRunWecomClient",
    "WebhookWecomClient",
    "WecomClient",
    "WecomPushError",
    "render_alert_card",
    "render_card_for_alert",
    "render_monthly_summary_card",
    "render_out_of_scope_card",
    "render_receipt_card",
    "render_work_order_card",
]
