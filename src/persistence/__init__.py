"""Persistence ports and SQLite adapters."""

from src.persistence.decision_store import DecisionStore
from src.persistence.idempotency_store import IdempotencyRecord, IdempotencyStore
from src.persistence.migrations import LATEST_SCHEMA_VERSION
from src.persistence.optimization_store import OptimizationPlanStore
from src.persistence.postgres import (
    PostgresDatabase,
    PostgresDecisionStore,
    PostgresIdempotencyStore,
    PostgresOptimizationPlanStore,
    PostgresRateLimiter,
    PostgresRevisionStore,
    PostgresSuggestionStore,
    PostgresWorkOrderStore,
    run_postgres_migrations,
)
from src.persistence.protocols import (
    DecisionRepository,
    IdempotencyRepository,
    OptimizationPlanRepository,
    RevisionRepository,
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
    "PostgresDatabase",
    "PostgresIdempotencyStore",
    "PostgresOptimizationPlanStore",
    "PostgresRateLimiter",
    "PostgresRevisionStore",
    "PostgresSuggestionStore",
    "PostgresWorkOrderStore",
    "IdempotencyRecord",
    "IdempotencyStore",
    "DecisionRepository",
    "IdempotencyRepository",
    "OptimizationPlanRepository",
    "RevisionRepository",
    "DecisionStore",
    "SuggestionRepository",
    "SuggestionStore",
    "WorkOrderRepository",
    "WorkOrderStore",
    "run_postgres_migrations",
]
