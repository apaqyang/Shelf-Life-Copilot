from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.observability import MetricsRegistry, log_event


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


def test_metrics_endpoint() -> None:
    response = TestClient(app).get("/metrics")
    assert response.status_code == 200
    assert "counters" in response.json()
