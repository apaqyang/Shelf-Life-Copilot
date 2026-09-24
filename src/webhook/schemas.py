"""Pydantic models for incoming WeCom callback payloads.

WeCom serializes its callback as PascalCase XML/JSON; we accept JSON in v0.1
(simpler local testing) and map the field names via alias_generators.
"""

from __future__ import annotations

import hashlib

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
    msg_id: str | None = None

    @property
    def stable_event_id(self) -> str:
        if self.msg_id:
            return f"wecom:{self.msg_id}"
        canonical = "\x1f".join(
            (
                self.to_user_name,
                self.from_user_name,
                str(self.create_time),
                self.msg_type,
                self.event or "",
                self.event_key or "",
                self.content or "",
            )
        )
        return f"wecom:{hashlib.sha256(canonical.encode()).hexdigest()}"


class WecomCallbackResponse(BaseModel):
    """Response shape we return to WeCom (and to tests for assertion)."""

    ok: bool
    detail: str
