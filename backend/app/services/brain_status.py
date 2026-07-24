"""Zero-IO status helpers for the text / image / video "brain" routing.

These are operational summaries for the owner UI: they explain which provider is
currently active for each modality and whether a configured fallback path exists.
No network calls happen here — this is pure config/runtime introspection.
"""

from __future__ import annotations

from typing import Any

from ..config import settings
from .llm import llm
from .media import _ffmpeg_exe


def _video_chain() -> list[str]:
    return [p.strip().lower() for p in (settings.VIDEO_PROVIDER or "reel").split(",") if p.strip()]


def text_brain_status() -> dict[str, Any]:
    flagship_provider, flagship_model = llm._failover(None, settings.MODEL_CHAT)
    fast_provider, fast_model = llm._failover(None, settings.MODEL_FAST)
    flagship_rescue = llm._rescue_chain(flagship_provider, flagship_model)
    fast_rescue = llm._rescue_chain(fast_provider, fast_model)
    return {
        "primary": {
            "provider": flagship_provider or "xai",
            "model": flagship_model,
            "configured": bool(settings.XAI_API_KEY or flagship_provider != "xai"),
        },
        "fast": {
            "provider": fast_provider or "xai",
            "model": fast_model,
        },
        "fallbacks": {
            "arena": bool(settings.ARENA_AI_API_KEY and settings.ARENA_AI_MODEL),
            "llm_fallback": bool(settings.LLM_FALLBACK_PROVIDER and settings.LLM_FALLBACK_MODEL),
            "freetheai": bool(settings.FREETHEAI_API_KEY and settings.FREETHEAI_MODEL),
            "extrabrain": bool(settings.EXTRA_BRAIN_API_KEY and settings.EXTRA_BRAIN_MODEL),
        },
        "rescue_chain": [{"provider": p or "xai", "model": m} for p, m in flagship_rescue],
        "fast_rescue_chain": [{"provider": p or "xai", "model": m} for p, m in fast_rescue],
        "ready": bool(flagship_model),
    }


def image_brain_status() -> dict[str, Any]:
    fallback = (settings.IMAGE_FALLBACK_PROVIDER or "").strip().lower()
    mode = "pollinations" if fallback == "pollinations" else "xai"
    return {
        "mode": mode,
        "primary": {
            "provider": mode,
            "model": settings.POLLINATIONS_MODEL if mode == "pollinations" else settings.MODEL_IMAGE,
        },
        "xai_configured": bool(settings.XAI_API_KEY),
        "fallback_provider": fallback or None,
        "pollinations": {
            "enabled": fallback == "pollinations",
            "model": settings.POLLINATIONS_MODEL,
            "url": settings.POLLINATIONS_IMAGE_URL,
        },
        "persist": bool(settings.IMAGE_PERSIST),
        "ready": bool((mode == "pollinations") or settings.XAI_API_KEY),
    }


def video_brain_status() -> dict[str, Any]:
    ffmpeg_ready = bool(_ffmpeg_exe())
    chain = _video_chain()
    providers = []
    for name in chain:
        if name == "reel":
            ready = bool(settings.REEL_ENABLED and ffmpeg_ready)
            reason = "ffmpeg ready" if ready else "needs ffmpeg + REEL_ENABLED=true"
        elif name == "pollinations":
            ready = bool(settings.POLLINATIONS_API_KEY)
            reason = "API key set" if ready else "needs POLLINATIONS_API_KEY"
        elif name == "xai":
            ready = bool(settings.XAI_API_KEY)
            reason = "xAI key set" if ready else "needs XAI_API_KEY"
        else:
            ready = False
            reason = "unknown provider"
        providers.append({"provider": name, "ready": ready, "reason": reason})

    narration_cloudflare = bool(
        settings.EMBED_API_KEY and (settings.EMBED_API_BASE_URL or "").startswith("https://api.cloudflare.com")
    )
    return {
        "chain": chain,
        "providers": providers,
        "ffmpeg": ffmpeg_ready,
        "reel_enabled": bool(settings.REEL_ENABLED),
        "storyboard": bool(settings.REEL_STORYBOARD),
        "narration": {
            "enabled": bool(settings.REEL_NARRATION),
            "extra_brain_tts": bool(settings.EXTRA_BRAIN_API_KEY),
            "cloudflare_aura": narration_cloudflare,
            "openai_soundtrack": bool(settings.OPENAI_API_KEY),
        },
        "ready": any(p["ready"] for p in providers),
    }


def brain_status() -> dict[str, Any]:
    return {
        "text": text_brain_status(),
        "image": image_brain_status(),
        "video": video_brain_status(),
    }
