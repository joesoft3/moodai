"""v1.9.1b — ⏱️ chat latency guards: hard time budgets + circuit breakers on context
sources; quota economy on the stand-in stack (titling + memory extraction paused)."""

import asyncio

import pytest

from app.api.routes import chat as chat_route
from app.config import settings
from app.services import memory as memory_svc


@pytest.fixture(autouse=True)
def _qdrant_mode(monkeypatch):
    # budget tests pin exact timeouts; pgvector mode intentionally raises the same-fate
    # floor to ≥8s (Neon wake-from-idle), so these tests force external-Qdrant semantics
    monkeypatch.setattr(settings, "VECTOR_BACKEND", "qdrant")


# ---------- hard budget on context sources ----------

def test_guarded_returns_none_on_slow_source(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_S", 0.1)

    async def _slow():
        await asyncio.sleep(5)
        return ["never"]

    out = asyncio.run(chat_route._guarded(lambda: _slow(), "test slow source"))
    assert out is None  # skipped, not stalled


def test_guarded_passes_through_fast_source(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_S", 2.0)

    async def _fast():
        return ["mem"]

    out = asyncio.run(chat_route._guarded(lambda: _fast(), "test fast source"))
    assert out == ["mem"]


def test_guarded_swallows_broken_source(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_S", 2.0)

    async def _broken():
        raise ConnectionError("All connection attempts failed")

    out = asyncio.run(chat_route._guarded(lambda: _broken(), "test broken source"))
    assert out is None


# ---------- circuit breaker ----------

def test_open_breaker_skips_source_instantly(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_S", 0.05)
    monkeypatch.setattr(settings, "CONTEXT_BREAKER_S", 60.0)
    chat_route._breaks.clear()
    calls = {"n": 0}

    async def _slow():
        calls["n"] += 1
        await asyncio.sleep(5)
        return None

    # 1st call: pays the small budget → trips the breaker
    assert asyncio.run(chat_route._guarded(lambda: _slow(), "src", breaker="test-q")) is None
    assert calls["n"] == 1
    # 2nd call: circuit open → factory never even invoked, zero wait
    assert asyncio.run(chat_route._guarded(lambda: _slow(), "src", breaker="test-q")) is None
    assert calls["n"] == 1
    chat_route._breaks.clear()


def test_breaker_expires_and_retries(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_S", 0.05)
    chat_route._breaks.clear()
    chat_route._breaks["test-e"] = 0.0  # long-expired breaker (monotonic epoch)

    async def _fast():
        return ["recovered"]

    out = asyncio.run(chat_route._guarded(lambda: _fast(), "src", breaker="test-e"))
    assert out == ["recovered"]
    chat_route._breaks.clear()


# ---------- quota economy on the stand-in stack ----------

def test_memory_extraction_paused_on_fallback(monkeypatch):
    monkeypatch.setattr(settings, "LLM_FALLBACK_PROVIDER", "gemini")

    async def _boom(*a, **kw):
        raise AssertionError("LLM must NOT be called for extraction while on the stand-in stack")

    monkeypatch.setattr(memory_svc.llm, "complete", _boom)
    asyncio.run(memory_svc.extract_and_store("u1", "hi", "hello"))  # returns quietly


def test_title_generation_paused_on_fallback(monkeypatch):
    monkeypatch.setattr(settings, "LLM_FALLBACK_PROVIDER", "gemini")

    async def _boom(*a, **kw):
        raise AssertionError("LLM must NOT be called for titling while on the stand-in stack")

    monkeypatch.setattr(chat_route.llm, "complete", _boom)
    asyncio.run(chat_route.generate_title("conv1", "hello there"))  # seeded title kept
