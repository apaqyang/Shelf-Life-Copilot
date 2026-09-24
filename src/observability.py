"""Small dependency-free structured logging and metrics primitives."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Mapping
from threading import Lock
from typing import Any


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    customer_id: str,
    correlation_id: str,
    result: str,
    duration_ms: float,
    **fields: object,
) -> None:
    """Emit one event with the stable fields consumed by log processors."""
    logger.log(
        level,
        event,
        extra={
            "event": event,
            "customer_id": customer_id,
            "correlation_id": correlation_id,
            "result": result,
            "duration_ms": round(duration_ms, 3),
            **fields,
        },
    )


class MetricsRegistry:
    """Thread-safe counters and duration aggregates suitable for one process."""

    def __init__(self) -> None:
        self._counters: dict[str, float] = defaultdict(float)
        self._durations: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def increment(self, name: str, value: float = 1) -> None:
        with self._lock:
            self._counters[name] += value

    def observe(self, name: str, value_ms: float) -> None:
        with self._lock:
            self._durations[name].append(value_ms)

    def snapshot(self) -> Mapping[str, Any]:
        with self._lock:
            durations = {
                name: {
                    "count": len(values),
                    "sum_ms": round(sum(values), 3),
                    "avg_ms": round(sum(values) / len(values), 3),
                }
                for name, values in self._durations.items()
                if values
            }
            return {"counters": dict(self._counters), "durations": durations}

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._durations.clear()


metrics = MetricsRegistry()
