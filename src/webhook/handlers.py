"""Click-event business logic — pure-ish (touches DB + filesystem, no HTTP).

EventKey contract: '<action>:<customer_id>:<batch_id>', e.g.
    approve:customerA:A-001
    snooze:customerA:A-001
    revise:customerA:A-001

approve/snooze land a Decision row; revise returns a prompt and writes nothing
(改方案 needs operator free-text, which is a separate message — out of v0.1
scope, see [[v0.5 SuggestionStore]] for the follow-up).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from src.models import ActionType, Decision, DecisionOutcome
from src.persistence import DecisionStore, SuggestionStore
from src.repository import load_batches
from src.webhook.schemas import WecomEvent

logger = logging.getLogger(__name__)


class UnknownActionError(ValueError):
    """Malformed or unrecognised EventKey — maps to HTTP 400."""


class UnknownBatchError(ValueError):
    """Customer or batch not found in mock data — maps to HTTP 404."""


_ACTION_KEY_TO_OUTCOME: dict[str, DecisionOutcome] = {
    "approve": DecisionOutcome.APPROVED,
    "snooze": DecisionOutcome.SNOOZED,
}

_REVISE_PROMPT = (
    "💬 改方案已收到。请直接在群里回复：『批号 改方案内容』"
    "（v0.1 暂不自动重生成，工程师会人工跟进 → 后续走 --revise-batch / --feedback）"
)


def _parse_event_key(event_key: str) -> tuple[str, str, str]:
    parts = event_key.split(":")
    if len(parts) != 3:
        raise UnknownActionError(
            f"EventKey must be 'action:customer_id:batch_id', got {event_key!r}"
        )
    return parts[0], parts[1], parts[2]


def handle_click(
    event: WecomEvent,
    store: DecisionStore,
    suggestion_store: SuggestionStore | None = None,
) -> str:
    """Route a click event to the right side effect, return a short status line.

    When `suggestion_store` is wired, approve/snooze decisions carry the real
    action + savings_estimate from the most recent LLM suggestion for that
    batch. Without it, or when no suggestion exists, we still land a Decision
    with TRANSFORM/0.0 placeholders + a WARNING so the audit log stays gap-free.
    """
    if not event.event_key:
        raise UnknownActionError("missing EventKey on click event")

    action_key, customer_id, batch_id = _parse_event_key(event.event_key)

    if action_key == "revise":
        return _REVISE_PROMPT

    outcome = _ACTION_KEY_TO_OUTCOME.get(action_key)
    if outcome is None:
        raise UnknownActionError(f"unknown action_key: {action_key!r}")

    try:
        batches = load_batches(customer_id)
    except FileNotFoundError as exc:
        raise UnknownBatchError(f"customer {customer_id!r} not found") from exc

    batch = next((b for b in batches if b.batch_id == batch_id), None)
    if batch is None:
        raise UnknownBatchError(f"batch {batch_id!r} not found for customer {customer_id!r}")

    action, savings_estimate = _resolve_action_and_savings(customer_id, batch_id, suggestion_store)

    decision = Decision(
        batch_id=batch.batch_id,
        customer_id=customer_id,
        material_name=batch.material_name,
        decided_at=datetime.now(UTC),
        action=action,
        outcome=outcome,
        savings_estimate=savings_estimate,
    )
    rowid = store.save(decision)
    return f"Recorded decision #{rowid} ({outcome.value})"


def _resolve_action_and_savings(
    customer_id: str,
    batch_id: str,
    suggestion_store: SuggestionStore | None,
) -> tuple[ActionType, float]:
    """Return (action, savings_estimate) for the new Decision.

    Prefer the latest LLM Suggestion for this batch when a store is available;
    fall back to TRANSFORM/0.0 placeholders + WARNING so the audit log stays
    complete even before SuggestionStore is wired into all call sites.
    """
    if suggestion_store is None:
        return ActionType.TRANSFORM, 0.0

    latest = suggestion_store.latest_for_batch(customer_id, batch_id)
    if latest is None:
        logger.warning(
            "Click on %s/%s but no suggestion found in store; "
            "Decision will use placeholder action/savings.",
            customer_id,
            batch_id,
        )
        return ActionType.TRANSFORM, 0.0

    return latest.action, latest.savings_estimate
