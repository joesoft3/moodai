"""pgvector brain — memory / recall / doc-RAG living inside the Postgres we already own.

Qdrant needed its own server; when none is provisioned (QDRANT_URL unset/localhost,
which was production reality) every semantic feature circuit-breakered OFF. This module
stores vectors in Neon Postgres via pgvector — one `vector_points` table, one row per
"point" (collection + id + embedding + jsonb payload) — and exposes a drop-in facade
for the tiny AsyncQdrantClient subset the app actually uses:

    get_collections / create_collection / create_payload_index
    upsert / query_points / scroll / retrieve / delete

so services/memory.py, services/recall.py and services/rag.py swap backends by changing
ONE factory (memory.qdrant) and nothing else. Cosine distance via pgvector's `<=>`;
payload filters (FieldCondition+MatchValue, must/must_not) translate to jsonb lookups.

The table is created by alembic migration 0020 in production AND lazily self-healed
here (CREATE EXTENSION/TABLE IF NOT EXISTS) so serverless hosts without a migration
step still boot straight into a working brain.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

import sqlalchemy as sa
from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue, PointIdsList

from ..config import settings
from ..db.session import SessionLocal

log = logging.getLogger(__name__)

_KEY_RE = re.compile(r"^[A-Za-z0-9_]+$")  # payload keys are app-internal constants — still validate


def pgvector_active() -> bool:
    """Should the pgvector backend serve vector requests?

    - "pgvector" → always
    - "qdrant"   → never
    - "auto"     → only when no real external Qdrant is configured (localhost/empty
                   QDRANT_URL means 'not provisioned' — measure production truth, not hope)
    """
    mode = (settings.VECTOR_BACKEND or "auto").strip().lower()
    if mode == "pgvector":
        return True
    if mode == "qdrant":
        return False
    q = (settings.QDRANT_URL or "").strip().lower()
    return not q or "localhost" in q or "127.0.0.1" in q or "[::1]" in q


def vector_literal(vec: list[float]) -> str:
    """pgvector text literal — CAST(:vec AS vector), no extra driver packages needed."""
    return "[" + ",".join(format(float(x), ".7g") for x in vec) + "]"


def _filter_sql(flt: Filter | None, params: dict, prefix: str = "f") -> str:
    """Translate a qdrant Filter (FieldCondition/MatchValue, must + must_not) to SQL."""
    clauses: list[str] = []

    def _conds(group) -> list[str]:
        out = []
        for i, cond in enumerate(group or []):
            if not isinstance(cond, FieldCondition) or not isinstance(getattr(cond, "match", None), MatchValue):
                continue  # range/geo matchers are unused in this codebase
            key = str(cond.key)
            if not _KEY_RE.match(key):
                raise ValueError(f"unsafe payload key in vector filter: {key!r}")
            pname = f"{prefix}{len(params)}"
            params[pname] = str(cond.match.value)
            out.append((key, pname, i))
        return out

    for key, pname, _ in _conds(getattr(flt, "must", None) if flt else None):
        clauses.append(f"payload->>'{key}' = :{pname}")
    for key, pname, _ in _conds(getattr(flt, "must_not", None) if flt else None):
        clauses.append(f"payload->>'{key}' IS DISTINCT FROM :{pname}")
    return " AND ".join(clauses) if clauses else "TRUE"


class _Col:
    def __init__(self, name: str):
        self.name = name


class _Collections:
    def __init__(self, names: list[str]):
        self.collections = [_Col(n) for n in names]


class _Point:
    __slots__ = ("id", "payload", "score", "vector")

    def __init__(self, pid: str, payload: dict, score: float | None = None):
        self.id = pid
        self.payload = payload
        self.score = score
        self.vector = None


class _QueryResult:
    def __init__(self, points: list[_Point]):
        self.points = points


class PgVectorStore:
    """AsyncQdrantClient-subset facade backed by the `vector_points` pgvector table."""

    def __init__(self) -> None:
        self._ensured = False
        self._lock = asyncio.Lock()

    async def _ensure(self) -> None:
        """One-time DDL (extension + table + index), serialized per process.

        Bug found live: a cold boot raced this DDL *inside* a user's request (multiple
        pending requests each ran it; one blocked past the 4s context budget → 300s
        circuit breaker → first minutes after a deploy ran memory-blind). The lock +
        retry make the race harmless: the loser re-runs idempotent DDL and succeeds.
        `_ensured` flips ONLY on success, so a failed attempt always self-heals later.
        """
        if self._ensured:
            return
        async with self._lock:
            if self._ensured:
                return
            dims = int(settings.EMBED_VECTOR_SIZE)
            last_err: Exception | None = None
            for _attempt in range(2):
                try:
                    async with SessionLocal() as db:
                        await db.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
                        await db.execute(
                            sa.text(
                                f"""
                                CREATE TABLE IF NOT EXISTS vector_points (
                                    collection text NOT NULL,
                                    id text NOT NULL,
                                    embedding vector({dims}),
                                    payload jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                                    created_at timestamptz NOT NULL DEFAULT now(),
                                    PRIMARY KEY (collection, id)
                                )
                                """
                            )
                        )
                        await db.execute(
                            sa.text(
                                "CREATE INDEX IF NOT EXISTS vector_points_user_idx "
                                "ON vector_points (collection, ((payload->>'user_id')))"
                            )
                        )
                        await db.commit()
                    self._ensured = True
                    return
                except Exception as e:  # concurrent bootstrap elsewhere — retry once
                    last_err = e
                    log.info("vector_points ensure attempt failed (retrying once): %s", e)
                    await asyncio.sleep(0.3)
            raise last_err  # type: ignore[misc]

    # ------------------------------------------------- collections (no-op-ish)
    async def get_collections(self) -> _Collections:
        await self._ensure()
        async with SessionLocal() as db:
            rows = (await db.execute(sa.text("SELECT DISTINCT collection FROM vector_points"))).scalars().all()
        return _Collections([str(r) for r in rows])

    async def create_collection(self, collection_name: str, **_: object) -> None:
        await self._ensure()  # single shared table — "creating" a collection = ensuring the store

    async def create_payload_index(self, *args: object, **kwargs: object) -> None:
        await self._ensure()  # user_id index lives in _ensure; other fields = jsonb seq-scan at our scale

    # ------------------------------------------------- writes
    async def upsert(self, collection_name: str, points: list, **_: object) -> None:
        await self._ensure()
        sql = sa.text(
            """
            INSERT INTO vector_points (collection, id, embedding, payload)
            VALUES (:col, :pid, CAST(:vec AS vector), CAST(:pay AS jsonb))
            ON CONFLICT (collection, id)
            DO UPDATE SET embedding = EXCLUDED.embedding, payload = EXCLUDED.payload
            """
        )
        async with SessionLocal() as db:
            for p in points:
                await db.execute(
                    sql,
                    {
                        "col": collection_name,
                        "pid": str(p.id),
                        "vec": vector_literal(list(p.vector)),
                        "pay": json.dumps(p.payload or {}),
                    },
                )
            await db.commit()

    async def delete(self, collection_name: str, points_selector=None, **_: object) -> None:
        await self._ensure()
        params: dict = {"col": collection_name}
        where = "collection = :col"
        if isinstance(points_selector, PointIdsList):
            params["ids"] = json.dumps([str(i) for i in (points_selector.points or [])])
            where += " AND id IN (SELECT jsonb_array_elements_text(CAST(:ids AS jsonb)))"
        elif isinstance(points_selector, FilterSelector):
            where += " AND " + _filter_sql(points_selector.filter, params)
        elif points_selector is not None:  # qdrant also accepts a bare list of ids
            params["ids"] = json.dumps([str(i) for i in points_selector])
            where += " AND id IN (SELECT jsonb_array_elements_text(CAST(:ids AS jsonb)))"
        async with SessionLocal() as db:
            await db.execute(sa.text(f"DELETE FROM vector_points WHERE {where}"), params)
            await db.commit()

    # ------------------------------------------------- reads
    async def query_points(
        self,
        collection_name: str,
        query: list[float],
        limit: int = 10,
        query_filter: Filter | None = None,
        with_payload: bool = True,
        **_: object,
    ) -> _QueryResult:
        await self._ensure()
        params: dict = {"col": collection_name, "vec": vector_literal(list(query)), "lim": int(limit)}
        where = "collection = :col AND " + _filter_sql(query_filter, params)
        sql = sa.text(
            f"""
            SELECT id, payload, 1 - (embedding <=> CAST(:vec AS vector)) AS score
            FROM vector_points
            WHERE {where} AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:vec AS vector) ASC
            LIMIT :lim
            """
        )
        async with SessionLocal() as db:
            rows = (await db.execute(sql, params)).mappings().all()
        return _QueryResult(
            [
                _Point(str(r["id"]), _payload(r["payload"]), round(float(r["score"]), 6))
                for r in rows
            ]
        )

    async def scroll(
        self,
        collection_name: str,
        scroll_filter: Filter | None = None,
        limit: int = 100,
        with_payload: bool = True,
        **_: object,
    ) -> tuple[list[_Point], None]:
        await self._ensure()
        params: dict = {"col": collection_name, "lim": int(limit)}
        where = "collection = :col AND " + _filter_sql(scroll_filter, params)
        sql = sa.text(
            f"SELECT id, payload FROM vector_points WHERE {where} ORDER BY created_at LIMIT :lim"
        )
        async with SessionLocal() as db:
            rows = (await db.execute(sql, params)).mappings().all()
        return [_Point(str(r["id"]), _payload(r["payload"])) for r in rows], None

    async def retrieve(
        self, collection_name: str, ids: list, with_payload: bool = True, **_: object
    ) -> list[_Point]:
        await self._ensure()
        sql = sa.text(
            "SELECT id, payload FROM vector_points WHERE collection = :col "
            "AND id IN (SELECT jsonb_array_elements_text(CAST(:ids AS jsonb)))"
        )
        async with SessionLocal() as db:
            rows = (
                await db.execute(sql, {"col": collection_name, "ids": json.dumps([str(i) for i in ids])})
            ).mappings().all()
        return [_Point(str(r["id"]), _payload(r["payload"])) for r in rows]


def _payload(raw) -> dict:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}
