"""Pydantic models for incoming WeCom callback payloads.

WeCom serializes its callback as PascalCase XML/JSON; we accept JSON in v0.1
(simpler local testing) and map the field names via alias_generators.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, alias_generators


class WecomEvent(BaseModel):
    """A WeCom callback message in JSON form.

    Only the fields we route on are required; extras (AgentID, MsgId, etc.) are
    accepted and ignored so we don't have to track every WeCom version's payload.
    """

    model_config = ConfigDict(
        alias_generator=alias_generators.to_pascal,
        populate_by_name=True,
        extra="ignore",
    )

    to_user_name: str
    from_user_name: str
    create_time: int
    msg_type: str
    event: str | None = None
    event_key: str | None = None
    content: str | None = None


class WecomCallbackResponse(BaseModel):
    """Response shape we return to WeCom (and to tests for assertion)."""

    ok: bool
    detail: str
