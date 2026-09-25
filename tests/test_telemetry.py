from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI

from src.telemetry import configure_otlp


def test_otlp_is_optional() -> None:
    configure_otlp(FastAPI(), endpoint=None, service_name="test")


def test_otlp_configures_exporter_processor_and_fastapi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    class Provider:
        def __init__(self, *, resource: object) -> None:
            calls["resource"] = resource

        def add_span_processor(self, processor: object) -> None:
            calls["processor"] = processor

    modules = {
        "opentelemetry.exporter.otlp.proto.http.trace_exporter": SimpleNamespace(
            OTLPSpanExporter=lambda *, endpoint: ("exporter", endpoint)
        ),
        "opentelemetry.instrumentation.fastapi": SimpleNamespace(
            FastAPIInstrumentor=SimpleNamespace(
                instrument_app=lambda app, *, tracer_provider: calls.update(
                    app=app, provider=tracer_provider
                )
            )
        ),
        "opentelemetry.sdk.resources": SimpleNamespace(
            Resource=SimpleNamespace(create=lambda values: values)
        ),
        "opentelemetry.sdk.trace": SimpleNamespace(TracerProvider=Provider),
        "opentelemetry.sdk.trace.export": SimpleNamespace(
            BatchSpanProcessor=lambda exporter: ("processor", exporter)
        ),
    }
    monkeypatch.setattr("src.telemetry.import_module", modules.__getitem__)
    app = FastAPI()
    configure_otlp(app, endpoint="https://collector/v1/traces", service_name="service")
    assert calls["resource"] == {"service.name": "service"}
    assert calls["processor"] == (
        "processor",
        ("exporter", "https://collector/v1/traces"),
    )
    assert calls["app"] is app
