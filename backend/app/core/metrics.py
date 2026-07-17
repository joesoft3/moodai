"""Prometheus metrics + stream tracking.

Exposed at GET /metrics (scrape with Prometheus / view in Grafana).
"""

from typing import AsyncGenerator

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response

REQ_COUNT = Counter(
    "mood_http_requests_total",
    "HTTP requests by route",
    ["method", "path", "status"],
)
REQ_LAT = Histogram(
    "mood_http_request_duration_seconds",
    "HTTP request latency (seconds, time-to-response; SSE measures time-to-first-byte)",
    ["method", "path"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)

LLM_COUNT = Counter(
    "mood_llm_requests_total",
    "LLM provider calls by model and kind (stream|complete|search|image)",
    ["model", "kind"],
)
LLM_LAT = Histogram(
    "mood_llm_request_duration_seconds",
    "LLM call duration (seconds)",
    ["model", "kind"],
    buckets=(0.25, 0.5, 1, 2, 5, 10, 20, 40, 90),
)
LLM_CHUNKS = Counter(
    "mood_llm_stream_chunks_total",
    "Streamed chunks relayed to clients",
    ["model"],
)
STREAMS_ACTIVE = Gauge(
    "mood_streams_active",
    "Currently open SSE streams (chat / agents / deepsearch)",
)


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def track_stream(agen: AsyncGenerator) -> AsyncGenerator:
    """Wrap an SSE event generator to count active streams."""
    STREAMS_ACTIVE.inc()
    try:
        async for item in agen:
            yield item
    finally:
        STREAMS_ACTIVE.dec()
