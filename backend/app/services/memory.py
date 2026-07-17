"""Long-term memory: extract durable user facts with a cheap model, embed locally,
store/retrieve in Qdrant (per-user scoped).

First embed triggers a one-time ~90 MB ONNX model download (fastembed).
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastembed import TextEmbedding
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
_embedder: TextEmbedding | None = None


def qdrant() -> AsyncQdrantClient:
    global _qdrant
    if _qdrant is None:
        _qdrant = AsyncQdrantClient(url=settings.QDRANT_URL)
    return _qdrant


def _get_embedder() -> TextEmbedding:
    global _embedder
    if _embedder is None:
        _embedder = TextEmbedding(settings.EMBED_MODEL)
    return _embedder


def _embed_sync(texts: list[str]) -> list[list[float]]:
    return [v.tolist() for v in _get_embedder().embed(texts)]


async def embed(texts: list[str]) -> list[list[float]]:
    return await asyncio.to_thread(_embed_sync, texts)


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
