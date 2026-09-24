"""Tenant identity and authorization rules shared by command endpoints."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException


@dataclass(frozen=True)
class Principal:
    subject: str
    customer_ids: frozenset[str]

    def require_customer(self, customer_id: str) -> None:
        if customer_id not in self.customer_ids:
            raise HTTPException(status_code=403, detail="customer access denied")
