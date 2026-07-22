"""v1.4.0 — 🔁 LLM failover: stand-in provider while xAI is down/unfunded."""

import asyncio

from app.config import Settings, settings
from app.services.llm import llm


def _env(monkeypatch, provider="gemini", model="gemini-2.5-flash", pro="gemini-2.5-pro", key="gk"):
    monkeypatch.setattr(settings, "LLM_FALLBACK_PROVIDER", provider)
    monkeypatch.setattr(settings, "LLM_FALLBACK_MODEL", model)
    monkeypatch.setattr(settings, "LLM_FALLBACK_MODEL_PRO", pro)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", key)


def test_failover_swaps_default_chat(monkeypatch):
    _env(monkeypatch)
    # flagship class → pro bucket (better answers + separate 429 pool)
    assert llm._failover(None, "grok-4") == ("gemini", "gemini-2.5-pro")


def test_failover_swaps_explicit_xai_picker_tiers(monkeypatch):
    _env(monkeypatch)
    # fast/mini class stays on the cheap fast bucket
    assert llm._failover("xai", "grok-4-fast") == ("gemini", "gemini-2.5-flash")
    assert llm._failover("xai", "grok-3-mini") == ("gemini", "gemini-2.5-flash")


def test_failover_leaves_non_xai_providers_alone(monkeypatch):
    _env(monkeypatch)
    assert llm._failover("gemini", "gemini-2.5-pro") == ("gemini", "gemini-2.5-pro")


def test_failover_requires_configured_provider_key(monkeypatch):
    _env(monkeypatch, key="")
    assert llm._failover(None, "grok-4") == (None, "grok-4")  # half-configured = no trap


def test_failover_off_by_default(monkeypatch):
    monkeypatch.setattr(settings, "LLM_FALLBACK_PROVIDER", "")
    monkeypatch.setattr(settings, "LLM_FALLBACK_MODEL", "")
    assert llm._failover(None, "grok-4") == (None, "grok-4")
    s = Settings(_env_file=None)
    assert s.LLM_FALLBACK_PROVIDER == "" and s.LLM_FALLBACK_MODEL == ""


def test_complete_swims_through_failover(monkeypatch):
    """complete() must reach the fallback provider with the fallback model."""
    _env(monkeypatch)
    calls = {}

    class _Completions:
        async def create(self, model, messages, **kw):
            calls["model"] = model
            class _Msg:  # minimal response duck
                content = "hi from fallback"
            class _Choice:
                message = _Msg()
            class _Resp:
                choices = [_Choice()]
                usage = None
            return _Resp()

    class _Client:
        class chat:
            completions = _Completions()

    monkeypatch.setattr(llm, "client_for", lambda provider: (calls.__setitem__("provider", provider), _Client())[1])
    out = asyncio.run(llm.complete([{"role": "user", "content": "hi"}]))
    assert out == "hi from fallback"
    assert calls["provider"] == "gemini" and calls["model"] == "gemini-2.5-flash"
