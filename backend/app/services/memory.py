"""Long-term memory: extract durable user facts with a cheap model, embed, and
store/retrieve semantically (per-user scoped).

Vector store (one factory — `qdrant()` — picks it; see services/vectorstore.py):
1. pgvector inside the app's own Postgres when no external Qdrant is provisioned
2. a real Qdrant when QDRANT_URL points at one

Embedding backends (EMBED_PROVIDER; auto order):
1. Gemini gemini-embedding-001 (GEMINI_API_KEY) — free, no model download, dims
   pinned to EMBED_VECTOR_SIZE so points stay compatible across providers
2. fastembed local ONNX — full hosts (first embed downloads ~90 MB once)
3. OpenAI-compatible /embeddings API (OPENAI_BASE_URL + EMBED_API_MODEL)

If none is available, embed() raises EmbeddingUnavailable; callers already
fail-open so chat keeps working with memory/RAG simply disabled.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx

try:  # heavy local embedder — optional so slim/serverless builds can skip it
    from fastembed import TextEmbedding
except Exception:  # pragma: no cover - exercised in slim deployments
    TextEmbedding = None
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PayloadSchemaType,
    PointIdsList,
    PointStruct,
    VectorParams,
)

from ..config import settings
from .llm import llm

log = logging.getLogger(__name__)

_qdrant: AsyncQdrantClient | None = None
_embedder: "TextEmbedding | None" = None


class EmbeddingUnavailable(RuntimeError):
    """No embedding backend configured (no fastembed install, no API key)."""


def qdrant():
    """Vector-store factory. Returns the real Qdrant client when an external server is
    configured, else the pgvector facade (services/vectorstore.py) — both expose the
    same small method surface, so every caller in memory/recall/rag stays agnostic."""
    global _qdrant
    if _qdrant is None:
        from .vectorstore import PgVectorStore, pgvector_active

        if pgvector_active():
            _qdrant = PgVectorStore()
        else:
            # hard client timeout: an unreachable vector store must fail in seconds,
            # never hold chat context assembly hostage (measured: dead endpoint ≈ 25s stall)
            _qdrant = AsyncQdrantClient(url=settings.QDRANT_URL, timeout=4)
    return _qdrant


def _get_embedder():
    global _embedder
    if _embedder is None:
        if TextEmbedding is None:
            raise EmbeddingUnavailable("fastembed is not installed in this environment")
        _embedder = TextEmbedding(settings.EMBED_MODEL)
    return _embedder


def _embed_sync(texts: list[str]) -> list[list[float]]:
    return [v.tolist() for v in _get_embedder().embed(texts)]


async def _embed_via_api(texts: list[str]) -> list[list[float]]:
    """OpenAI-compatible embeddings (middle rescue tier: any gateway with an
    /embeddings route — Cloudflare Workers AI bge models, Voyage proxies, etc.).
    EMBED_API_KEY / EMBED_API_BASE_URL override the voice-path OPENAI_* pair so
    embeddings can live on a different provider entirely. Asks for
    EMBED_VECTOR_SIZE dims so vectors match the pgvector table; providers that
    don't support the dimensions param get a lean retry."""
    key = settings.EMBED_API_KEY or settings.OPENAI_API_KEY
    base = (settings.EMBED_API_BASE_URL or settings.OPENAI_BASE_URL or "").rstrip("/")
    if not key:
        raise EmbeddingUnavailable(
            "no local fastembed and no EMBED_API_KEY/OPENAI_API_KEY configured for the embeddings API"
        )
    headers = {"Authorization": f"Bearer {key}"}
    payload: dict = {"model": settings.EMBED_API_MODEL, "input": texts}
    if settings.EMBED_VECTOR_SIZE:
        payload["dimensions"] = settings.EMBED_VECTOR_SIZE
    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=30) as client:
        r = await client.post("/embeddings", json=payload)
        if r.status_code == 400 and "dimensions" in payload:
            # provider doesn't support dimension hints — retry minimal payload
            payload.pop("dimensions", None)
            r = await client.post("/embeddings", json=payload)
        r.raise_for_status()
    data = r.json().get("data") or []
    return [d["embedding"] for d in sorted(data, key=lambda d: d.get("index", 0))]


async def _embed_via_gemini(texts: list[str]) -> list[list[float]]:
    """Gemini embeddings (free tier) — dims pinned to EMBED_VECTOR_SIZE so the stored
    points match across providers. Batch endpoint first, single calls as fallback.
    GEMINI_EMBED_API_KEY lets a SECOND Google key (separate daily quota) serve
    embeddings while the main key handles chat."""
    key = settings.GEMINI_EMBED_API_KEY or settings.GEMINI_API_KEY
    if not key:
        raise EmbeddingUnavailable("no Gemini API key configured for embeddings")
    model = settings.GEMINI_EMBED_MODEL

    def _part(t: str) -> dict:
        return {
            "model": f"models/{model}",
            "content": {"parts": [{"text": t[:9000]}]},
            "outputDimensionality": int(settings.EMBED_VECTOR_SIZE),
        }

    base = f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            f"{base}:batchEmbedContents",
            params={"key": key},
            json={"requests": [_part(t) for t in texts]},
        )
        if r.status_code == 200:
            embs = r.json().get("embeddings") or []
            if len(embs) == len(texts):
                return [[float(x) for x in e["values"]] for e in embs]
            raise EmbeddingUnavailable("gemini batch returned an unexpected embedding count")
        # 429s/errors surface here if singles fail too — callers' circuit breakers handle it
        out: list[list[float]] = []
        for t in texts:
            rr = await client.post(f"{base}:embedContent", params={"key": key}, json=_part(t))
            rr.raise_for_status()
            out.append([float(x) for x in rr.json()["embedding"]["values"]])
        return out


async def embed(texts: list[str]) -> list[list[float]]:
    provider = (settings.EMBED_PROVIDER or "auto").strip().lower()
    if provider in ("auto", "gemini") and (settings.GEMINI_EMBED_API_KEY or settings.GEMINI_API_KEY):
        try:
            return await _embed_via_gemini(texts)
        except Exception as e:
            if provider == "gemini":
                raise EmbeddingUnavailable(f"gemini embeddings failed: {e}") from e
            log.warning("gemini embeddings failed, trying next embedder: %s", e)
    # OpenAI-compatible middle tier (a fast network call beats the 90MB local ONNX
    # download + CPU on small hosts; CF Workers AI bge-small is 384-dim like us)
    if provider in ("auto", "openai") and (settings.EMBED_API_KEY or settings.OPENAI_API_KEY):
        try:
            return await _embed_via_api(texts)
        except Exception as e:
            if provider == "openai":
                raise EmbeddingUnavailable(f"embeddings API failed: {e}") from e
            log.warning("embeddings API failed, trying local embedder: %s", e)
    if provider in ("auto", "fastembed") and TextEmbedding is not None:
        return await asyncio.to_thread(_embed_sync, texts)
    raise EmbeddingUnavailable(f"no embedding backend available (EMBED_PROVIDER={provider})")


async def init_memory_collection() -> None:
    c = qdrant()
    existing = await c.get_collections()
    names = {col.name for col in existing.collections}
    if settings.MEMORY_COLLECTION not in names:
        await c.create_collection(
            settings.MEMORY_COLLECTION,
            vectors_config=VectorParams(size=settings.EMBED_VECTOR_SIZE, distance=Distance.COSINE),
        )
    try:
        await c.create_payload_index(settings.MEMORY_COLLECTION, "user_id", PayloadSchemaType.KEYWORD)
        await c.create_payload_index(settings.MEMORY_COLLECTION, "kind", PayloadSchemaType.KEYWORD)
    except Exception:
        pass


def _user_filter(user_id: str) -> Filter:
    return Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))])


def _facts_filter(user_id: str) -> Filter:
    """User scope, excluding cross-conversation recall points (kind='chat')."""
    return Filter(
        must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))],
        must_not=[FieldCondition(key="kind", match=MatchValue(value="chat"))],
    )


async def retrieve_memories(user_id: str, query: str, top_k: int | None = None) -> list[dict]:
    vec = (await embed([query]))[0]
    res = await qdrant().query_points(
        collection_name=settings.MEMORY_COLLECTION,
        query=vec,
        limit=top_k or settings.MEMORY_TOP_K,
        query_filter=_facts_filter(user_id),
        with_payload=True,
    )
    return [
        {"id": str(p.id), **(p.payload or {}), "score": round(float(p.score or 0), 3)}
        for p in res.points
        if (p.score or 0) >= 0.30
    ]


EXTRACT_PROMPT = """Extract durable long-term memories about the USER from the exchange.
Return STRICT JSON only, no prose:
{"memories":[{"fact":"...","category":"preference|profile|project|interest|other"}]}

Rules:
- Facts must come from EXPLICIT USER statements ONLY. The ASSISTANT's examples, riffs
  or opinions are NEVER user facts (live drill: assistant joked "hard to beat jollof"
  and it was wrongly stored as the user's favourite food).
- Only stable facts useful across many future chats (identity, preferences, projects, constraints).
- Skip small talk, transient questions, secrets, or one-off data.
- Max 3 items. If nothing is worth remembering, return {"memories":[]}."""


def _strip_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


async def extract_and_store(user_id: str, user_msg: str, assistant_msg: str, plan: str = "free") -> None:
    # Quota economy (QUOTA_ECONOMY=1): fact extraction (1 LLM call/message) pauses as a
    # daily-budget shield for tiny provider keys; chat answers alone consume the quota.
    # Off by default — memory writing stays live; retrieval is never affected either way.
    if settings.QUOTA_ECONOMY:
        return
    try:
        raw = await llm.complete(
            [
                {"role": "system", "content": EXTRACT_PROMPT},
                {"role": "user", "content": f"USER: {user_msg[:2000]}\n\nASSISTANT: {assistant_msg[:2000]}"},
            ],
            temperature=0.0,
            max_tokens=300,
        )
        items = json.loads(_strip_fence(raw)).get("memories") or []
        facts = [i for i in items if isinstance(i, dict) and i.get("fact")][:3]
        if not facts:
            return
        vectors = await embed([f["fact"].strip() for f in facts])
        points = []
        for f, v in zip(facts, vectors):
            fact = f["fact"].strip()
            pid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{user_id}:{fact.lower()}"))  # upsert = dedupe
            points.append(
                PointStruct(
                    id=pid,
                    vector=v,
                    payload={
                    "user_id": user_id,
                    "kind": "fact",
                    "fact": fact,
                    "category": str(f.get("category", "other"))[:24],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                )
            )
        await qdrant().upsert(settings.MEMORY_COLLECTION, points)
        # 🧰 Pro perk: plan-based memory retention (free 30d / pro 365d)
        try:
            from .metering import PLAN_LIMITS

            keep_days = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"]).get("mem_days", 0)
            if keep_days:
                await prune_old_memories(user_id, keep_days)
        except Exception as e:
            log.debug("memory retention prune skipped: %s", e)
    except Exception as e:
        log.warning("memory extraction failed: %s", e)


async def prune_old_memories(user_id: str, keep_days: int) -> int:
    """Delete this user's recall points (facts + chat digests) older than `keep_days`.

    Points without a timestamp (legacy) are kept. Fail-open; returns count deleted.
    """
    from qdrant_client.models import PointIdsList

    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    points, _ = await qdrant().scroll(
        collection_name=settings.MEMORY_COLLECTION,
        scroll_filter=_user_filter(user_id),
        limit=1000,
        with_payload=True,
    )
    doomed: list[str] = []
    for p in points:
        pay = p.payload or {}
        ts = pay.get("created_at") or pay.get("updated_at")
        if not ts:
            continue
        try:
            when = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when < cutoff:
                doomed.append(str(p.id))
        except Exception:
            continue
    if doomed:
        await qdrant().delete(settings.MEMORY_COLLECTION, points_selector=PointIdsList(points=doomed))
        log.info("memory retention: pruned %d points (> %sd) for %s", len(doomed), keep_days, user_id)
    return len(doomed)


async def list_memories(user_id: str) -> list[dict]:
    points, _ = await qdrant().scroll(
        collection_name=settings.MEMORY_COLLECTION,
        scroll_filter=_user_filter(user_id),
        limit=200,
        with_payload=True,
    )
    return [{"id": str(p.id), **(p.payload or {})} for p in points]


async def delete_memory(user_id: str, point_id: str) -> bool:
    found = await qdrant().retrieve(settings.MEMORY_COLLECTION, [point_id], with_payload=True)
    if not found or (found[0].payload or {}).get("user_id") != user_id:
        return False
    await qdrant().delete(settings.MEMORY_COLLECTION, points_selector=PointIdsList(points=[point_id]))
    return True


async def clear_memories(user_id: str) -> None:
    await qdrant().delete(settings.MEMORY_COLLECTION, points_selector=FilterSelector(filter=_user_filter(user_id)))
