"""v1.9.1 — 🛟 LLM resilience: class-aware fallback mapping + instant sibling-bucket
rescue on 429 (no SDK backoff sleeps inside the stand-in stack)."""

import asyncio

import httpx
from openai import RateLimitError

from app.config import settings
from app.services.llm import llm


def _env(monkeypatch):
    monkeypatch.setattr(settings, "LLM_FALLBACK_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "LLM_FALLBACK_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(settings, "LLM_FALLBACK_MODEL_PRO", "gemini-2.5-pro")
    monkeypatch.setattr(settings, "LLM_FALLBACK_429_SWAP", True)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "gk")


def _rlerror() -> RateLimitError:
    req = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
    return RateLimitError("quota exceeded", response=httpx.Response(429, request=req), body=None)


# ---------- class-aware failover mapping ----------

def test_flagship_goes_to_pro_bucket(monkeypatch):
    _env(monkeypatch)
    assert llm._failover(None, "grok-4") == ("gemini", "gemini-2.5-pro")
    assert llm._failover("xai", "grok-4.1") == ("gemini", "gemini-2.5-pro")


def test_fast_and_mini_stay_on_flash_bucket(monkeypatch):
    _env(monkeypatch)
    assert llm._failover(None, "grok-4-fast") == ("gemini", "gemini-2.5-flash")
    assert llm._failover(None, "grok-3-mini") == ("gemini", "gemini-2.5-flash")
    assert llm._failover(None, "grok-code-fast-1") == ("gemini", "gemini-2.5-flash")


def test_pro_env_empty_falls_back_to_single_bucket(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(settings, "LLM_FALLBACK_MODEL_PRO", "")
    assert llm._failover(None, "grok-4") == ("gemini", "gemini-2.5-flash")


# ---------- rescue-chain mapping ----------

def test_rescue_swaps_fallback_buckets_both_ways(monkeypatch):
    _env(monkeypatch)
    assert llm._rescue_chain("gemini", "gemini-2.5-flash") == [("gemini", "gemini-2.5-pro")]
    assert llm._rescue_chain("gemini", "gemini-2.5-pro") == [("gemini", "gemini-2.5-flash")]


def test_rescue_never_engages_outside_configured_providers(monkeypatch):
    _env(monkeypatch)
    assert llm._rescue_chain("xai", "grok-4") == []
    assert llm._rescue_chain(None, "grok-4") == []
    assert llm._rescue_chain("openai", "gpt-4o") == []


def test_rescue_respects_kill_switch(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(settings, "LLM_FALLBACK_429_SWAP", False)
    assert llm._rescue_chain("gemini", "gemini-2.5-flash") == []


# ---------- 429 rescue through complete() ----------

def test_complete_429_swims_to_sibling(monkeypatch):
    _env(monkeypatch)
    calls: list[str] = []

    class _Completions:
        async def create(self, model, messages, **kw):
            calls.append(model)
            if len(calls) == 1:
                raise _rlerror()
            class _Msg:
                content = "rescued by sibling"
            class _Choice:
                message = _Msg()
            class _Resp:
                choices = [_Choice()]
                usage = None
            return _Resp()

    class _Client:
        class chat:
            completions = _Completions()

    monkeypatch.setattr(llm, "client_for", lambda provider: _Client())
    out = asyncio.run(llm.complete([{"role": "user", "content": "hi"}], model="grok-3-mini"))
    # grok-3-mini → flash bucket → 429 → rescued by pro bucket
    assert out == "rescued by sibling"
    assert calls == ["gemini-2.5-flash", "gemini-2.5-pro"]


def test_complete_429_raises_when_both_buckets_saturated(monkeypatch):
    _env(monkeypatch)
    calls: list[str] = []

    class _Completions:
        async def create(self, model, messages, **kw):
            calls.append(model)
            raise _rlerror()

    class _Client:
        class chat:
            completions = _Completions()

    monkeypatch.setattr(llm, "client_for", lambda provider: _Client())

    def _run():
        return asyncio.run(llm.complete([{"role": "user", "content": "hi"}], model="grok-3-mini"))

    try:
        _run()
        assert False, "expected RateLimitError"
    except RateLimitError:
        pass
    assert calls == ["gemini-2.5-flash", "gemini-2.5-pro"]  # exactly one rescue attempt


# ---------- 429 rescue through stream_chat() ----------

def test_stream_429_swims_to_sibling(monkeypatch):
    _env(monkeypatch)
    calls: list[str] = []

    class _Delta:
        content = "stream-rescued"
        reasoning_content = None

    class _Choice:
        delta = _Delta()

    class _Chunk:
        choices = [_Choice()]
        usage = None
        citations = None

    class _Stream:
        def __aiter__(self):
            async def gen():
                yield _Chunk()
            return gen()

    class _Completions:
        async def create(self, model, messages, **kw):
            calls.append(model)
            if len(calls) == 1:
                raise _rlerror()
            return _Stream()

    class _Client:
        class chat:
            completions = _Completions()

    monkeypatch.setattr(llm, "client_for", lambda provider: _Client())

    async def _collect():
        out = []
        async for ev in llm.stream_chat([{"role": "user", "content": "hi"}], model="grok-4"):
            out.append(ev)
        return out

    events = asyncio.run(_collect())
    # grok-4 → pro bucket → 429 → rescued by flash bucket
    assert calls == ["gemini-2.5-pro", "gemini-2.5-flash"]
    assert any(e.get("type") == "delta" and "stream-rescued" in e.get("text", "") for e in events)


# ---------- fallback client skips SDK retries ----------

def test_fallback_client_disables_sdk_retries(monkeypatch):
    _env(monkeypatch)
    llm._clients.pop("gemini", None)
    c = llm.client_for("gemini")
    assert c.max_retries == 0
