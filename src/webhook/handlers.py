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

from datetime import UTC, datetime

from src.models import ActionType, Decision, DecisionOutcome
from src.persistence import DecisionStore
from src.repository import load_batches
from src.webhook.schemas import WecomEvent


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


def handle_click(event: WecomEvent, store: DecisionStore) -> str:
    """Route a click event to the right side effect, return a short status line."""
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

    # v0.1 placeholders — action / savings_estimate come from the original
    # Suggestion once SuggestionStore lands. Until then we record the click
    # event itself so the monthly report at least sees a non-zero count.
    decision = Decision(
        batch_id=batch.batch_id,
        customer_id=customer_id,
        material_name=batch.material_name,
        decided_at=datetime.now(UTC),
        action=ActionType.TRANSFORM,
        outcome=outcome,
        savings_estimate=0.0,
    )
    rowid = store.save(decision)
    return f"Recorded decision #{rowid} ({outcome.value})"
