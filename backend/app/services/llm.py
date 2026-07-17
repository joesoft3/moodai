"""xAI (Grok) service — OpenAI-compatible chat, vision, live search and image APIs.

Every model name and the base URL are env-configurable, so this same client can be
pointed at any OpenAI-compatible provider (the multi-provider router seam).

All calls are instrumented: mood_llm_requests_total / mood_llm_request_duration_seconds
/ mood_llm_stream_chunks_total (see core/metrics).
"""

import logging
import time
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from ..config import settings
from ..core.metrics import LLM_CHUNKS, LLM_COUNT, LLM_LAT

log = logging.getLogger(__name__)


class LLMNotConfigured(Exception):
    pass


def friendly_ai_error(exc: Exception) -> str:
    if isinstance(exc, LLMNotConfigured):
        return "AI provider not configured — set XAI_API_KEY (get one at https://console.x.ai)."
    s = str(exc)
    if "401" in s or "api key" in s.lower() or "authentication" in s.lower():
        return "AI provider authentication failed — check XAI_API_KEY."
    return f"AI request failed: {s[:240]}"


SEARCH_PARAMS: dict[str, Any] = {
    "mode": "auto",  # model decides when to search
    "return_citations": True,
    "sources": [{"type": "web"}, {"type": "x"}, {"type": "news"}],
}


class LLMService:
    """OpenAI-compatible client with a provider registry + per-task router.

    Providers are env-driven: xai (default), gemini, openai — a provider with no
    API key is skipped by the router (falls back to xai). Claude can be added via
    any OpenAI-compat gateway (e.g. LiteLLM) by pointing OPENAI_BASE_URL at it.
    """

    _clients: dict[str, AsyncOpenAI] = {}

    def _provider_specs(self) -> dict[str, tuple[str, str]]:
        """key → (base_url, api_key)."""
        return {
            "xai": (settings.XAI_BASE_URL, settings.XAI_API_KEY),
            "gemini": (settings.GEMINI_BASE_URL, settings.GEMINI_API_KEY),
            "openai": (settings.OPENAI_BASE_URL, settings.OPENAI_API_KEY),
        }

    def provider_available(self, key: str) -> bool:
        spec = self._provider_specs().get(key)
        return bool(spec and spec[1])

    def client_for(self, provider: str | None) -> AsyncOpenAI:
        key = provider or "xai"
        if key not in self._clients:
            base_url, api_key = self._provider_specs()[key]
            if not api_key:
                raise LLMNotConfigured(f"Provider '{key}' has no API key set.")
            self._clients[key] = AsyncOpenAI(api_key=api_key, base_url=base_url)
        return self._clients[key]

    @property
    def client(self) -> AsyncOpenAI:
        return self.client_for("xai")

    def route(self, task: str) -> tuple[str, str]:
        """task (chat|coding|agents|deepsearch) → (provider, model).

        Routing away from xAI requires BOTH: the provider's API key set AND a
        ROUTE_MODEL_<TASK> override — otherwise it deterministically falls back
        to xAI. Safe against half-configured envs."""
        t = task.upper()
        if t == "FAST":
            return "xai", settings.MODEL_FAST
        want = (getattr(settings, f"PROVIDER_{t}", "xai") or "xai").lower()
        override = (getattr(settings, f"ROUTE_MODEL_{t}", "") or "").strip()
        if want != "xai" and override and self.provider_available(want):
            return want, override
        return "xai", settings.MODEL_CHAT

    async def stream_chat(
        self,
        messages: list[dict],
        model: str,
        enable_search: bool = False,
        provider: str | None = None,
        think: bool = False,
    ) -> AsyncIterator[dict]:
        LLM_COUNT.labels(model=model, kind="stream").inc()
        t0 = time.perf_counter()
        try:
            kwargs: dict[str, Any] = {}
            if enable_search and provider in (None, "xai"):  # Live Search is an xAI feature
                kwargs["extra_body"] = {"search_parameters": SEARCH_PARAMS}
            if think and provider in (None, "xai") and "mini" in model:
                # only the mini family takes an explicit effort knob; grok-4 reasons by default
                kwargs.setdefault("extra_body", {})["reasoning_effort"] = "high"
            stream = await self.client_for(provider).chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                temperature=0.7,
                stream_options={"include_usage": True},  # final chunk carries token usage
                **kwargs,
            )
            usage: dict = {}
            async for chunk in stream:
                u = getattr(chunk, "usage", None)
                if u:
                    usage = {
                        "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
                        "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
                    }
                citations = getattr(chunk, "citations", None)  # xAI live-search citations
                if citations:
                    yield {"type": "citations", "citations": list(citations)}
                if not chunk.choices:
                    continue
                if think:
                    # 🧠 xAI reasoning models emit live reasoning_content deltas (grok-4 default,
                    # grok-3-mini at high effort) — surfaced as thinking traces by the route.
                    rc = getattr(chunk.choices[0].delta, "reasoning_content", None)
                    if rc:
                        yield {"type": "reasoning", "text": rc}
                text = getattr(chunk.choices[0].delta, "content", None)
                if text:
                    LLM_CHUNKS.labels(model=model).inc()
                    yield {"type": "delta", "text": text}
            if usage:
                yield {"type": "usage", "usage": usage}  # routes meter this; not forwarded to clients
        finally:
            LLM_LAT.labels(model=model, kind="stream").observe(time.perf_counter() - t0)

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        usage_out: dict | None = None,  # pass a dict to receive provider token usage
        provider: str | None = None,
    ) -> str:
        m = model or settings.MODEL_FAST
        LLM_COUNT.labels(model=m, kind="complete").inc()
        t0 = time.perf_counter()
        try:
            resp = await self.client_for(provider).chat.completions.create(
                model=m,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if usage_out is not None:
                u = getattr(resp, "usage", None)
                if u:
                    usage_out["prompt_tokens"] = getattr(u, "prompt_tokens", 0) or 0
                    usage_out["completion_tokens"] = getattr(u, "completion_tokens", 0) or 0
            return resp.choices[0].message.content or ""
        finally:
            LLM_LAT.labels(model=m, kind="complete").observe(time.perf_counter() - t0)

    async def complete_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str | None = None,
        provider: str | None = None,
    ) -> Any:
        """One function-calling round. Returns the raw assistant message object
        (inspect .tool_calls; convert with .model_dump(exclude_none=True) to re-append)."""
        m = model or settings.MODEL_CHAT
        LLM_COUNT.labels(model=m, kind="complete").inc()
        t0 = time.perf_counter()
        try:
            resp = await self.client_for(provider).chat.completions.create(
                model=m, messages=messages, tools=tools, tool_choice="auto", temperature=0.2
            )
            return resp.choices[0].message
        finally:
            LLM_LAT.labels(model=m, kind="complete").observe(time.perf_counter() - t0)

    async def complete_with_search(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.4,
        usage_out: dict | None = None,
        provider: str | None = None,
    ) -> tuple[str, list[str]]:
        """Non-streaming completion with xAI Live Search. Returns (text, citations).
        Live Search is xAI-only — other providers should use plain complete()."""
        m = model or settings.MODEL_CHAT
        LLM_COUNT.labels(model=m, kind="search").inc()
        t0 = time.perf_counter()
        try:
            extra: dict[str, Any] = {}
            if provider in (None, "xai"):
                extra["extra_body"] = {"search_parameters": SEARCH_PARAMS}
            resp = await self.client_for(provider).chat.completions.create(
                model=m, messages=messages, temperature=temperature, **extra
            )
            if usage_out is not None:
                u = getattr(resp, "usage", None)
                if u:
                    usage_out["prompt_tokens"] = getattr(u, "prompt_tokens", 0) or 0
                    usage_out["completion_tokens"] = getattr(u, "completion_tokens", 0) or 0
            citations = getattr(resp, "citations", None) or []
            return (resp.choices[0].message.content or "", list(citations))
        finally:
            LLM_LAT.labels(model=m, kind="search").observe(time.perf_counter() - t0)

    async def generate_image(self, prompt: str) -> str | None:
        m = settings.MODEL_IMAGE
        LLM_COUNT.labels(model=m, kind="image").inc()
        t0 = time.perf_counter()
        try:
            res = await self.client.images.generate(model=m, prompt=prompt, n=1)
            d = res.data[0]
            if getattr(d, "url", None):
                return d.url
            b64 = getattr(d, "b64_json", None)
            return f"data:image/png;base64,{b64}" if b64 else None
        finally:
            LLM_LAT.labels(model=m, kind="image").observe(time.perf_counter() - t0)


llm = LLMService()
