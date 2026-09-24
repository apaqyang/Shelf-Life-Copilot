"""Persistence ports and SQLite adapters."""

from src.persistence.decision_store import DecisionStore
from src.persistence.idempotency_store import IdempotencyRecord, IdempotencyStore
from src.persistence.migrations import LATEST_SCHEMA_VERSION
from src.persistence.optimization_store import OptimizationPlanStore
from src.persistence.postgres import (
    PostgresDecisionStore,
    PostgresSuggestionStore,
    PostgresWorkOrderStore,
    run_postgres_migrations,
)
from src.persistence.protocols import (
    DecisionRepository,
    SuggestionRepository,
    WorkOrderRepository,
)
from src.persistence.revision_store import RevisionSession, RevisionStore
from src.persistence.suggestion_store import SuggestionStore
from src.persistence.work_order_store import WorkOrderStore

__all__ = [
    "LATEST_SCHEMA_VERSION",
    "OptimizationPlanStore",
    "RevisionSession",
    "RevisionStore",
    "PostgresDecisionStore",
    "PostgresSuggestionStore",
    "PostgresWorkOrderStore",
    "IdempotencyRecord",
    "IdempotencyStore",
    "DecisionRepository",
    "DecisionStore",
    "SuggestionRepository",
    "SuggestionStore",
    "WorkOrderRepository",
    "WorkOrderStore",
    "run_postgres_migrations",
]
