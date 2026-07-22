"""v1.9.2 — 🥇 Arena.ai first-brain seam (dormant by default).

When Arena.ai opens its developer API, setting ARENA_AI_API_KEY + ARENA_AI_MODEL
makes Arena the first brain for every xAI-bound call, with an automatic 429
cascade down to the Gemini stand-in stack. Zero behavior change while unset."""

import asyncio

import httpx
from openai import RateLimitError

from app.config import Settings, settings
from app.services.llm import llm


def _env(monkeypatch, arena_key="ak", arena_model="arena-1", arena_fast="arena-1-fast"):
    monkeypatch.setattr(settings, "ARENA_AI_API_KEY", arena_key)
    monkeypatch.setattr(settings, "ARENA_AI_MODEL", arena_model)
    monkeypatch.setattr(settings, "ARENA_AI_MODEL_FAST", arena_fast)
    monkeypatch.setattr(settings, "LLM_FALLBACK_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "LLM_FALLBACK_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(settings, "LLM_FALLBACK_MODEL_PRO", "gemini-2.5-pro")
    monkeypatch.setattr(settings, "LLM_FALLBACK_429_SWAP", True)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "gk")


def _rlerror() -> RateLimitError:
    req = httpx.Request("POST", "https://api.arena.ai/v1/chat/completions")
    return RateLimitError("quota exceeded", response=httpx.Response(429, request=req), body=None)


# ---------- defaults: entirely off ----------

def test_arena_seam_off_by_default():
    s = Settings(_env_file=None)
    assert s.ARENA_AI_API_KEY == "" and s.ARENA_AI_MODEL == ""
    assert llm._failover(None, "grok-4") == (None, "grok-4")  # untouched without envs


# ---------- first-brain routing ----------

def test_arena_preempts_xai_when_configured(monkeypatch):
    _env(monkeypatch)
    assert llm._failover(None, "grok-4") == ("arena", "arena-1")
    assert llm._failover("xai", "grok-4.1") == ("arena", "arena-1")


def test_arena_fast_tier_uses_fast_model(monkeypatch):
    _env(monkeypatch)
    assert llm._failover(None, "grok-4-fast") == ("arena", "arena-1-fast")
    assert llm._failover(None, "grok-3-mini") == ("arena", "arena-1-fast")


def test_arena_fast_defaults_to_flagship_when_unset(monkeypatch):
    _env(monkeypatch, arena_fast="")
    assert llm._failover(None, "grok-4-fast") == ("arena", "arena-1")


def test_no_key_means_no_arena_even_with_model(monkeypatch):
    _env(monkeypatch, arena_key="")
    # falls through to the gemini stand-in stack instead
    assert llm._failover(None, "grok-4") == ("gemini", "gemini-2.5-pro")


def test_explicit_non_xai_providers_untouched_by_arena(monkeypatch):
    _env(monkeypatch)
    assert llm._failover("openai", "gpt-4o") == ("openai", "gpt-4o")
    assert llm._failover("gemini", "gemini-2.5-pro") == ("gemini", "gemini-2.5-pro")


# ---------- 429 cascade: arena → gemini, class preserved ----------

def test_rescue_cascades_arena_flagship_to_pro_bucket(monkeypatch):
    _env(monkeypatch)
    assert llm._rescue_chain("arena", "arena-1") == [("gemini", "gemini-2.5-pro"), ("gemini", "gemini-2.5-flash")]


def test_rescue_cascades_arena_fast_to_flash_bucket(monkeypatch):
    _env(monkeypatch)
    assert llm._rescue_chain("arena", "arena-1-fast") == [("gemini", "gemini-2.5-flash"), ("gemini", "gemini-2.5-pro")]


def test_rescue_none_when_arena_has_no_backup(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(settings, "LLM_FALLBACK_PROVIDER", "")
    assert llm._rescue_chain("arena", "arena-1") == []


def test_complete_cascades_arena_429_to_gemini(monkeypatch):
    _env(monkeypatch)
    calls: list[tuple[str, str]] = []

    class _Raise429:
        async def create(self, model, messages, **kw):
            calls.append(("arena", model))
            raise _rlerror()

    class _Answer:
        async def create(self, model, messages, **kw):
            calls.append(("gemini", model))

            class _Msg:
                content = "gemini rescued the arena brain"
            class _Choice:
                message = _Msg()
            class _Resp:
                choices = [_Choice()]
                usage = None
            return _Resp()

    class _Client429:
        class chat:
            completions = _Raise429()

    class _ClientOK:
        class chat:
            completions = _Answer()

    dispatch = {"arena": _Client429(), "gemini": _ClientOK()}
    monkeypatch.setattr(llm, "client_for", lambda provider: dispatch[provider])
    out = asyncio.run(llm.complete([{"role": "user", "content": "hi"}], model="grok-4"))
    assert out == "gemini rescued the arena brain"
    assert calls == [("arena", "arena-1"), ("gemini", "gemini-2.5-pro")]


def test_arena_client_disables_sdk_retries(monkeypatch):
    _env(monkeypatch)
    llm._clients.pop("arena", None)
    c = llm.client_for("arena")
    assert c.max_retries == 0
    assert c.base_url.host == "api.arena.ai"
