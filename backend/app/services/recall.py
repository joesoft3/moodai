"""Cross-conversation recall ("chat memory").

Mood remembers *what previous conversations were about* — not just extracted
facts. Two complementary parts:

1.  Rolling summaries in Postgres — ``conversations.summary`` is refreshed as a
    conversation grows (with the cheap model tier), so a one-paragraph digest of
    every past chat is always available.
2.  Embedded digests in Qdrant — each summary is upserted into the shared
    ``user_memories`` collection with ``kind="chat"`` (facts are ``kind="fact"``
    and are stored/read with ``must_not kind='chat'``, so the two never mix).
    A chat request semantically retrieves whichever *past conversations* are
    relevant to the current message ("what did we decide about the flights?"),
    and brand-new conversations also get a digest of the most recent previous
    chats so "last time we…" / "continue where we left off" works directly.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct
from sqlalchemy import select

from ..config import settings
from ..db.models import Conversation, Message
from ..db.session import SessionLocal
from .memory import embed, qdrant

log = logging.getLogger(__name__)

SUMMARY_SYSTEM = (
    "You maintain a running third-person digest of a conversation between the user "
    "and an AI assistant called Mood. Rules: max 90 words; keep decisions made, "
    "concrete names/dates/numbers, stated preferences and the conversation's goal; "
    "drop small talk; update the existing digest rather than restarting it; reply "
    "with ONLY the digest text, no preamble."
)


async def update_conversation_summary(user_id, conv_id) -> None:
    """Refresh the rolling summary + vector digest for one conversation.

    Fire-and-forget background task (chat / agents / deepsearch / voice routes
    invoke it after an exchange is persisted). Fully guarded — recall must
    never break a chat.
    """
    try:
        async with SessionLocal() as db:
            conv = await db.get(Conversation, conv_id)
            if not conv or str(conv.user_id) != str(user_id):
                return
            res = await db.execute(
                select(Message.role, Message.content)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.created_at)
            )
            rows = [(r, c) for r, c in res.all() if c]
            # Debounce: first exchange, then every other one (LLM-cost control).
            if len(rows) < 2 or (len(rows) != 2 and len(rows) % 4 != 2):
                return
            transcript = "\n".join(
                f"{'ASSISTANT' if r == 'assistant' else 'USER'}: {c[:900]}" for r, c in rows[-16:]
            )
            msgs = [{"role": "system", "content": SUMMARY_SYSTEM}]
            if conv.summary:
                msgs.append({"role": "user", "content": f"Existing digest (update it):\n{conv.summary}"})
            msgs.append({"role": "user", "content": f"Write the updated digest for this conversation:\n\n{transcript}"})

            from .llm import llm

            digest = (
                await llm.complete(msgs, model=settings.MODEL_FAST, temperature=0.2, max_tokens=220)
            ).strip()[:800]
            if not digest:
                return
            conv.summary = digest
            await db.commit()

            vec = (await embed([f"{conv.title}\n{digest}"]))[0]
            payload = {
                "user_id": str(user_id),
                "kind": "chat",
                "category": "chat",  # settings UI splits past-conversation entries on this
                "fact": digest,      # generic fact-style renderers read `fact`
                "conversation_id": str(conv.id),
                "title": conv.title,
                "summary": digest,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                await qdrant().upsert(
                    collection_name=settings.MEMORY_COLLECTION,
                    points=[
                        PointStruct(
                            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"chat:{conv.id}")),
                            vector=vec,
                            payload=payload,
                        )
                    ],
                )
            except Exception as e:  # Qdrant hiccup — SQL summary is still kept
                log.warning("chat digest embed failed (SQL summary kept): %s", e)
    except Exception as e:
        log.warning("update_conversation_summary failed: %s", e)


async def retrieve_past_chats(user_id, query: str, exclude_conv_id=None, top_k: int | None = None) -> list[dict]:
    """Semantic search over this user's past *conversation digests*."""
    try:
        vec = (await embed([query]))[0]
        qfilter = Filter(
            must=[
                FieldCondition(key="user_id", match=MatchValue(value=str(user_id))),
                FieldCondition(key="kind", match=MatchValue(value="chat")),
            ]
        )
        res = await qdrant().query_points(
            collection_name=settings.MEMORY_COLLECTION,
            query=vec,
            limit=(top_k or settings.RECALL_TOP_K) * 2,
            query_filter=qfilter,
            with_payload=True,
        )
        out: list[dict] = []
        for p in res.points:
            pay = p.payload or {}
            if exclude_conv_id and str(pay.get("conversation_id")) == str(exclude_conv_id):
                continue
            if (p.score or 0) < settings.RECALL_MIN_SCORE:
                continue
            out.append(
                {
                    "conversation_id": str(pay.get("conversation_id", "")),
                    "title": pay.get("title", "untitled"),
                    "summary": pay.get("summary", ""),
                    "updated_at": pay.get("updated_at"),
                    "score": round(float(p.score or 0), 3),
                }
            )
            if len(out) >= (top_k or settings.RECALL_TOP_K):
                break
        return out
    except Exception as e:
        log.debug("retrieve_past_chats failed: %s", e)
        return []


async def purge_conversation_summary(conv_id) -> None:
    """Drop a conversation's recall vector. Fail-open."""
    try:
        from qdrant_client.models import PointIdsList

        await qdrant().delete(
            collection_name=settings.MEMORY_COLLECTION,
            points_selector=PointIdsList(points=[str(uuid.uuid5(uuid.NAMESPACE_URL, f"chat:{conv_id}"))]),
        )
    except Exception as e:
        log.debug("purge_conversation_summary failed: %s", e)


async def delete_chat_memory(user_id, conv_id) -> None:
    """Forget one conversation everywhere (route calls this right after the row delete).

    The Postgres summary disappears with the conversation row; the Qdrant recall
    vector needs an explicit purge.
    """
    await purge_conversation_summary(conv_id)


async def recent_chat_summaries(db, user_id, exclude_conv_id=None, limit: int | None = None):
    """Newest conversations that already have a summary (the literal 'previous chats').

    Returns SQLAlchemy rows with ``.title`` / ``.summary`` / ``.updated_at``.
    """
    limit = limit or settings.RECENT_CHATS_DIGEST
    stmt = (
        select(Conversation.title, Conversation.summary, Conversation.updated_at, Conversation.id)
        .where(
            Conversation.user_id == user_id,
            Conversation.summary.isnot(None),
            Conversation.summary != "",
        )
        .order_by(Conversation.updated_at.desc())
        .limit(limit + (1 if exclude_conv_id else 0))
    )
    res = await db.execute(stmt)
    rows = [r for r in res.all() if not exclude_conv_id or str(r.id) != str(exclude_conv_id)]
    return rows[:limit]
