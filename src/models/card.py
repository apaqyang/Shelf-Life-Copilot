"""Card model — value object representing one WeCom card payload.

A Card is the final artifact produced by `src/wecom/cards.py` and consumed by
a `WecomClient`. It is intentionally renderer-agnostic: `markdown` is what gets
posted to a WeCom markdown message, while `buttons` and `mentioned_userids` are
side-band metadata that a future template_card renderer can use.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CardKind(StrEnum):
    """The four card templates v0.1 must render (PRD §5.3 / TODO Week 2)."""

    ALERT = "alert"
    WORK_ORDER = "work_order"
    RECEIPT = "receipt"
    OUT_OF_SCOPE = "out_of_scope"


def _now_utc() -> datetime:
    return datetime.now(UTC)


class CardButton(BaseModel):
    """A button rendered at the bottom of a card. v0.1 demo prints the label inline."""

    model_config = ConfigDict(frozen=True)

    label: str = Field(min_length=1)
    action_key: str = Field(min_length=1)


class Card(BaseModel):
    """A WeCom-ready card payload.

    `is_standard=False` means the suggested action is outside the customer's
    enabled_actions and renderers should add a red "⚠️ 非标准动作 · 需人工复核"
    banner at the top — see `render_out_of_scope_card`.
    """

    model_config = ConfigDict(frozen=True)

    kind: CardKind
    customer_id: str
    batch_id: str
    title: str = Field(min_length=1)
    markdown: str = Field(min_length=1)
    buttons: list[CardButton] = Field(default_factory=list)
    mentioned_userids: list[str] = Field(default_factory=list)
    is_standard: bool = True
    generated_at: datetime = Field(default_factory=_now_utc)
