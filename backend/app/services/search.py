"""Alternative search provider (Tavily) — sample of the provider-plug pattern.

Primary path is xAI Live Search via search_parameters on the chat request
(see services/llm.py). Set SEARCH_PROVIDER=tavily to use this instead: snippets
are injected as context instead of enabling Live Search.
"""

import logging

import httpx

from ..config import settings

log = logging.getLogger(__name__)


async def tavily_context(query: str, max_results: int = 5) -> str:
    if not settings.TAVILY_API_KEY:
        return ""
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.TAVILY_API_KEY,
                    "query": query,
                    "max_results": max_results,
                    "include_answer": True,
                },
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning("tavily search failed: %s", e)
        return ""
    parts: list[str] = []
    if data.get("answer"):
        parts.append("Summary: " + data["answer"])
    for i, res in enumerate(data.get("results", []), 1):
        parts.append(
            f"[{i}] {res.get('title', '')} — {res.get('url', '')}\n{(res.get('content') or '')[:400]}"
        )
    return "\n\n".join(parts)
