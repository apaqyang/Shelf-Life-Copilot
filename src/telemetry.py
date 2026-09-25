"""Optional OpenTelemetry OTLP exporter wiring."""

from __future__ import annotations

from importlib import import_module

from fastapi import FastAPI


def configure_otlp(app: FastAPI, *, endpoint: str | None, service_name: str) -> None:
    """Instrument FastAPI when an OTLP endpoint is explicitly configured."""
    if endpoint is None:
        return
    try:
        exporter_module = import_module("opentelemetry.exporter.otlp.proto.http.trace_exporter")
        fastapi_module = import_module("opentelemetry.instrumentation.fastapi")
        resource_module = import_module("opentelemetry.sdk.resources")
        trace_module = import_module("opentelemetry.sdk.trace")
        export_module = import_module("opentelemetry.sdk.trace.export")
    except ModuleNotFoundError as exc:  # pragma: no cover - deployment dependency
        raise RuntimeError("OTLP export requires the 'observability' project extra") from exc
    resource = resource_module.Resource.create({"service.name": service_name})
    provider = trace_module.TracerProvider(resource=resource)
    exporter = exporter_module.OTLPSpanExporter(endpoint=endpoint)
    provider.add_span_processor(export_module.BatchSpanProcessor(exporter))
    fastapi_module.FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
