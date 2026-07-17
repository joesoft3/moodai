"""Document RAG (Phase 2 of file intelligence — ARCHITECTURE.md §7):
uploaded documents are chunked, embedded locally and stored in Qdrant.
At chat time, relevant chunks from the user's library are retrieved
semantically and injected as context.
"""

import logging
import uuid

from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from ..config import settings
from .memory import embed, qdrant  # reuse the embedder + client singletons

log = logging.getLogger(__name__)

DOC_COLLECTION = "doc_chunks"
CHUNK_SIZE = 900
CHUNK_OVERLAP = 150
MAX_CHUNKS_PER_DOC = 100


def _chunks(text: str) -> list[str]:
    out, i = [], 0
    while i < len(text):
        piece = text[i : i + CHUNK_SIZE]
        if piece.strip():
            out.append(piece)
        i += CHUNK_SIZE - CHUNK_OVERLAP
    return out[:MAX_CHUNKS_PER_DOC]


async def init_doc_collection() -> None:
    c = qdrant()
    existing = await c.get_collections()
    if DOC_COLLECTION not in {col.name for col in existing.collections}:
        await c.create_collection(
            DOC_COLLECTION,
            vectors_config=VectorParams(size=settings.EMBED_VECTOR_SIZE, distance=Distance.COSINE),
        )
    for field in ("user_id", "file_id"):
        try:
            await c.create_payload_index(DOC_COLLECTION, field, PayloadSchemaType.KEYWORD)
        except Exception:
            pass


async def index_document(user_id: str, file_id: str, filename: str, text: str | None) -> int:
    """Chunk + embed + upsert a document. Run as a background task. Returns chunk count."""
    if not text:
        return 0
    try:
        chunks = _chunks(text)
        vectors = await embed(chunks)
        points = [
            PointStruct(
                id=str(uuid.uuid4()),
                vector=v,
                payload={
                    "user_id": user_id,
                    "file_id": file_id,
                    "filename": filename,
                    "chunk_index": idx,
                    "text": chunk,
                },
            )
            for idx, (chunk, v) in enumerate(zip(chunks, vectors))
        ]
        await qdrant().upsert(DOC_COLLECTION, points)
        log.info("indexed %s into %d chunks", filename, len(points))
        return len(points)
    except Exception as e:
        log.warning("document indexing failed for %s: %s", filename, e)
        return 0


async def delete_document_chunks(file_id: str) -> None:
    try:
        await qdrant().delete(
            DOC_COLLECTION,
            points_selector=FilterSelector(
                filter=Filter(must=[FieldCondition(key="file_id", match=MatchValue(value=file_id))])
            ),
        )
    except Exception as e:
        log.warning("chunk cleanup failed for %s: %s", file_id, e)


async def retrieve_doc_chunks(
    user_id: str,
    query: str,
    limit: int = 5,
    exclude_file_ids: set[str] | None = None,
) -> list[dict]:
    """Semantic search over the user's document library."""
    vec = (await embed([query]))[0]
    res = await qdrant().query_points(
        collection_name=DOC_COLLECTION,
        query=vec,
        limit=limit * 2,  # over-fetch; filter below
        query_filter=Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]),
        with_payload=True,
    )
    exclude = exclude_file_ids or set()
    out: list[dict] = []
    for p in res.points:
        if (p.score or 0) < 0.35:
            continue
        pay = p.payload or {}
        if pay.get("file_id") in exclude:
            continue  # attached files are already inline in the prompt
        out.append(
            {
                "filename": pay.get("filename", "document"),
                "file_id": pay.get("file_id"),
                "score": round(float(p.score or 0), 3),
                "text": pay.get("text", ""),
            }
        )
        if len(out) >= limit:
            break
    return out
