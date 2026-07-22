"""v1.9.3 — 🥈 FreeTheAi extra-brain seam (dormant by default).

With FREETHEAI_API_KEY + FREETHEAI_MODEL set, the free OpenAI-compatible gateway
(freetheai.xyz) joins the brain cascade as always-on extra capacity: it becomes the
first brain when no higher tier is configured, and always backs every 429 rescue
chain with class-preserved FreeTheAi buckets. Zero behavior change while unset."""

import asyncio

import httpx
from openai import RateLimitError

from app.config import Settings, settings
from app.services.llm import llm


def _env(monkeypatch, gemini_on=True):
    monkeypatch.setattr(settings, "ARENA_AI_API_KEY", "")
    monkeypatch.setattr(settings, "ARENA_AI_MODEL", "")
    if gemini_on:
        monkeypatch.setattr(settings, "LLM_FALLBACK_PROVIDER", "gemini")
        monkeypatch.setattr(settings, "LLM_FALLBACK_MODEL", "gemini-3-flash-preview")
        monkeypatch.setattr(settings, "LLM_FALLBACK_MODEL_PRO", "gemini-3.6-flash")
        monkeypatch.setattr(settings, "LLM_FALLBACK_429_SWAP", True)
        monkeypatch.setattr(settings, "GEMINI_API_KEY", "gk")
    else:
        monkeypatch.setattr(settings, "LLM_FALLBACK_PROVIDER", "")
        monkeypatch.setattr(settings, "LLM_FALLBACK_MODEL", "")
    monkeypatch.setattr(settings, "FREETHEAI_API_KEY", "fk")
    monkeypatch.setattr(settings, "FREETHEAI_MODEL", "ft-flagship")
    monkeypatch.setattr(settings, "FREETHEAI_MODEL_FAST", "ft-fast")


def _rlerror() -> RateLimitError:
    req = httpx.Request("POST", "https://api.freetheai.xyz/v1/chat/completions")
    return RateLimitError("quota exceeded", response=httpx.Response(429, request=req), body=None)


# ---------- defaults: entirely off ----------

def test_freetheai_seam_off_by_default():
    s = Settings(_env_file=None)
    assert s.FREETHEAI_API_KEY == "" and s.FREETHEAI_MODEL == ""
    assert llm._failover(None, "grok-4") == (None, "grok-4")


# ---------- first-brain ordering ----------

def test_gemini_keeps_first_brain_when_both_configured(monkeypatch):
    _env(monkeypatch, gemini_on=True)
    assert llm._failover(None, "grok-4") == ("gemini", "gemini-3.6-flash")


def test_freetheai_becomes_first_brain_when_gemini_unset(monkeypatch):
    _env(monkeypatch, gemini_on=False)
    assert llm._failover(None, "grok-4") == ("freetheai", "ft-flagship")
    assert llm._failover(None, "grok-4-fast") == ("freetheai", "ft-fast")


def test_freetheai_fast_defaults_to_flagship(monkeypatch):
    _env(monkeypatch, gemini_on=False)
    monkeypatch.setattr(settings, "FREETHEAI_MODEL_FAST", "")
    assert llm._failover(None, "grok-4-fast") == ("freetheai", "ft-flagship")


# ---------- rescue chain composition ----------

def test_gemini_chains_end_in_freetheai_capacity(monkeypatch):
    _env(monkeypatch, gemini_on=True)
    assert llm._rescue_chain("gemini", "gemini-3.6-flash") == [
        ("gemini", "gemini-3-flash-preview"),     # sibling bucket first
        ("freetheai", "ft-flagship"),             # then FreeTheAi, class-preserved
        ("freetheai", "ft-fast"),
    ]
    assert llm._rescue_chain("gemini", "gemini-3-flash-preview") == [
        ("gemini", "gemini-3.6-flash"),
        ("freetheai", "ft-fast"),
        ("freetheai", "ft-flagship"),
    ]


def test_freetheai_bucket_swaps_itself_last(monkeypatch):
    _env(monkeypatch, gemini_on=True)
    assert llm._rescue_chain("freetheai", "ft-flagship") == [("freetheai", "ft-fast")]
    assert llm._rescue_chain("freetheai", "ft-fast") == [("freetheai", "ft-flagship")]


# ---------- full cascade integration through complete() ----------

def test_complete_walks_full_cascade_to_freetheai(monkeypatch):
    _env(monkeypatch, gemini_on=True)
    monkeypatch.setattr(settings, "ARENA_AI_API_KEY", "ak")
    monkeypatch.setattr(settings, "ARENA_AI_MODEL", "arena-1")
    monkeypatch.setattr(settings, "ARENA_AI_MODEL_FAST", "arena-1-fast")
    calls: list[tuple[str, str]] = []

    class _Raise429:
        def __init__(self, provider):
            self.provider = provider

        async def create(self, model, messages, **kw):
            calls.append((self.provider, model))
            raise _rlerror()

    class _Answer:
        def __init__(self, provider):
            self.provider = provider

        async def create(self, model, messages, **kw):
            calls.append((self.provider, model))

            class _Msg:
                content = "answered by the free brain"
            class _Choice:
                message = _Msg()
            class _Resp:
                choices = [_Choice()]
                usage = None
            return _Resp()

    class _Client:
        def __init__(self, inner):
            class chat:
                completions = inner
            self.chat = chat()

    dispatch = {
        "arena": _Client(_Raise429("arena")),
        "gemini": _Client(_Raise429("gemini")),
        "freetheai": _Client(_Answer("freetheai")),
    }
    monkeypatch.setattr(llm, "client_for", lambda provider: dispatch[provider])
    out = asyncio.run(llm.complete([{"role": "user", "content": "hi"}], model="grok-4"))
    assert out == "answered by the free brain"
    assert calls == [
        ("arena", "arena-1"),
        ("gemini", "gemini-3.6-flash"),
        ("gemini", "gemini-3-flash-preview"),
        ("freetheai", "ft-flagship"),
    ]


def test_freetheai_client_disables_sdk_retries(monkeypatch):
    _env(monkeypatch)
    llm._clients.pop("freetheai", None)
    c = llm.client_for("freetheai")
    assert c.max_retries == 0
    assert c.base_url.host == "api.freetheai.xyz"
