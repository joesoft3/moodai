"""Optional OpenTelemetry tracing — enabled by setting OTEL_EXPORTER_OTLP_ENDPOINT.

Quick local trace viewer:
    docker run -p 16686:16686 -p 4318:4318 jaegertracing/all-in-one
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
    → open http://localhost:16686 (service: mood-ai-api)
"""

import logging

from .config import settings

log = logging.getLogger(__name__)


def setup_tracing(app) -> bool:
    endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT
    if not endpoint:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": "mood-ai-api"}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")))
        trace.set_tracer_provider(provider)

        FastAPIInstrumentor.instrument_app(app)
        # openai + qdrant clients run on httpx → provider calls become spans automatically
        HTTPXClientInstrumentor().instrument()

        log.info("OpenTelemetry tracing enabled → %s", endpoint)
        return True
    except Exception as e:
        log.warning("OpenTelemetry setup failed (tracing disabled): %s", e)
        return False
