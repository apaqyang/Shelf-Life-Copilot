from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.main import app
from src.observability import (
    MetricsRegistry,
    TraceContextMiddleware,
    log_event,
    trace_headers,
)


def test_structured_log_fields(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test.structured")
    caplog.set_level(logging.INFO, logger="test.structured")
    log_event(
        logger,
        logging.INFO,
        "scan.completed",
        customer_id="c1",
        correlation_id="trace",
        result="success",
        duration_ms=1.23456,
    )
    record = caplog.records[-1]
    assert record.customer_id == "c1"
    assert record.correlation_id == "trace"
    assert record.result == "success"
    assert record.duration_ms == 1.235


def test_metrics_snapshot_and_reset() -> None:
    registry = MetricsRegistry()
    registry.increment("ok")
    registry.increment("ok", 2)
    registry.observe("latency", 10)
    registry.observe("latency", 20)
    assert registry.snapshot() == {
        "counters": {"ok": 3.0},
        "durations": {"latency": {"count": 2, "sum_ms": 30, "avg_ms": 15}},
    }
    registry.reset()
    assert registry.snapshot() == {"counters": {}, "durations": {}}
    assert registry.render_prometheus() == ""


def test_prometheus_rendering_normalizes_names_and_durations() -> None:
    registry = MetricsRegistry()
    registry.increment("1.bad-name", 2)
    registry.observe("scan.duration", 12.5)
    output = registry.render_prometheus()
    assert "shelf_life_1_bad_name 2" in output
    assert "scan_duration_milliseconds_count 1" in output
    assert "scan_duration_milliseconds_sum 12.5" in output


def test_metrics_endpoint() -> None:
    response = TestClient(app).get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# TYPE" in response.text


def test_w3c_trace_context_is_continued_and_reset() -> None:
    traced = FastAPI()
    traced.add_middleware(TraceContextMiddleware)

    @traced.get("/")
    async def endpoint() -> dict[str, str]:
        return trace_headers()

    incoming = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
    with TestClient(traced) as client:
        continued = client.get("/", headers={"traceparent": incoming})
        generated = client.get("/", headers={"traceparent": "invalid"})
    assert continued.headers["traceparent"].startswith("00-0123456789abcdef0123456789abcdef-")
    assert continued.json()["traceparent"] == continued.headers["traceparent"]
    assert generated.headers["traceparent"].startswith("00-")
    assert len(generated.headers["traceparent"]) == 55
    assert trace_headers() == {}
