"""Small dependency-free structured logging and metrics primitives."""

from __future__ import annotations

import logging
import re
import secrets
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from threading import Lock
from typing import Any, cast

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")
_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_span_id: ContextVar[str | None] = ContextVar("span_id", default=None)


def current_traceparent() -> str | None:
    trace_id = _trace_id.get()
    span_id = _span_id.get()
    return None if trace_id is None or span_id is None else f"00-{trace_id}-{span_id}-01"


def trace_headers() -> dict[str, str]:
    traceparent = current_traceparent()
    return {} if traceparent is None else {"traceparent": traceparent}


class TraceContextMiddleware(BaseHTTPMiddleware):
    """Continue W3C trace context and expose it to outbound adapters."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get("traceparent", "")
        match = _TRACEPARENT.fullmatch(incoming)
        trace_id = match.group(1) if match is not None else secrets.token_hex(16)
        trace_token = _trace_id.set(trace_id)
        span_token = _span_id.set(secrets.token_hex(8))
        try:
            response = await call_next(request)
            response.headers["traceparent"] = current_traceparent() or ""
            return response
        finally:
            _span_id.reset(span_token)
            _trace_id.reset(trace_token)


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

    def render_prometheus(self) -> str:
        """Render a Prometheus text exposition snapshot for multi-instance scraping."""
        snapshot = self.snapshot()
        lines: list[str] = []
        counters = cast(dict[str, float], snapshot["counters"])
        durations = cast(dict[str, dict[str, float]], snapshot["durations"])
        for raw_name, value in sorted(counters.items()):
            name = _metric_name(raw_name)
            lines.extend((f"# TYPE {name} counter", f"{name} {value:g}"))
        for raw_name, values in sorted(durations.items()):
            name = _metric_name(raw_name)
            lines.extend(
                (
                    f"# TYPE {name}_milliseconds summary",
                    f"{name}_milliseconds_count {values['count']:g}",
                    f"{name}_milliseconds_sum {values['sum_ms']:g}",
                )
            )
        return "\n".join(lines) + ("\n" if lines else "")


def _metric_name(name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_:]", "_", name)
    if not normalized or normalized[0].isdigit():
        normalized = f"shelf_life_{normalized}"
    return normalized


metrics = MetricsRegistry()
