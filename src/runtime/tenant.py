"""Tenant identity and authorization rules shared by command endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from fastapi import HTTPException


class Role(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


@dataclass(frozen=True)
class Principal:
    subject: str
    customer_ids: frozenset[str]
    roles: frozenset[Role] = frozenset({Role.VIEWER})

    def has_any_role(self, roles: frozenset[Role]) -> bool:
        return bool(self.roles & roles)

    def require_customer(self, customer_id: str) -> None:
        if customer_id not in self.customer_ids:
            raise HTTPException(status_code=403, detail="customer access denied")
