"""SQLite-backed persistence for Decision log entries.

v0.1 uses sqlite3 (stdlib, zero deps) — sufficient for single-process / single-customer
deployments. v0.5 will swap the implementation for PostgreSQL behind the same
DecisionStore API.
"""

from src.persistence.decision_store import DecisionStore
from src.persistence.suggestion_store import SuggestionStore

__all__ = ["DecisionStore", "SuggestionStore"]
