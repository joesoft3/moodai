"""v1.9.1b — ⏱️ chat latency guards: context sources get a hard time budget;
quota economy on the stand-in stack (titling + memory extraction paused)."""

import asyncio

from app.api.routes import chat as chat_route
from app.config import settings
from app.services import memory as memory_svc


# ---------- hard budget on context sources ----------

def test_guarded_returns_none_on_slow_source(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_S", 0.1)

    async def _slow():
        await asyncio.sleep(5)
        return ["never"]

    out = asyncio.run(chat_route._guarded(_slow(), "test slow source"))
    assert out is None  # skipped, not stalled


def test_guarded_passes_through_fast_source(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_S", 2.0)

    async def _fast():
        return ["mem"]

    out = asyncio.run(chat_route._guarded(_fast(), "test fast source"))
    assert out == ["mem"]


def test_guarded_swallows_broken_source(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_S", 2.0)

    async def _broken():
        raise ConnectionError("All connection attempts failed")

    out = asyncio.run(chat_route._guarded(_broken(), "test broken source"))
    assert out is None


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
