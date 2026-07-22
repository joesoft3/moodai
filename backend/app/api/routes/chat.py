"""Streaming chat orchestrator: auth → context assembly (memory + files + search)
→ model routing → SSE stream → background memory extraction & titling.
"""

import asyncio
import json
import logging
import time
from datetime import date, datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.metrics import track_stream
from ...db.models import Conversation, FileAsset, Message, User
from ...db.session import SessionLocal, get_db
from ...schemas import ChatRequest, ImageRequest
from ...services.file_extract import image_data_url
from ...services.llm import friendly_ai_error, llm
from ...services.memory import extract_and_store, retrieve_memories
from ...services.metering import estimate_tokens, plan_rate_mult, record_usage
from ...services.plugins import resolve_plugins
from ...services.rag import retrieve_doc_chunks
from ...services.recall import recent_chat_summaries, retrieve_past_chats, update_conversation_summary
from ...services.search import tavily_context
from ..deps import enforce_rate_limit, get_current_user

router = APIRouter()
log = logging.getLogger(__name__)

# 🚀 Premium model picker: client-selectable models (absent/"auto" = routed default).
MODEL_CHOICES = {
    "grok-4": settings.MODEL_CHAT,
    "grok-4-fast": settings.MODEL_CHAT_FAST,
    "grok-3-mini": settings.MODEL_FAST,
    "grok-code-fast-1": settings.MODEL_CODE,
}
# 🧠 Only these emit live reasoning traces (matches the web/mobile pickers).
THINKABLE_MODELS = {settings.MODEL_CHAT, settings.MODEL_CODE}


async def summarize_thinking(trace: str) -> str | None:
    """2-sentence user-friendly digest of a long reasoning trace (fast model, fail-open)."""
    if not trace.strip():
        return None
    try:
        out = await llm.complete(
            [
                {
                    "role": "user",
                    "content": "Summarize this AI reasoning in 2 short sentences for the user — what was considered and what approach was chosen:\n\n"
                    + trace[-4000:],
                }
            ],
            max_tokens=120,
        )
        return out.strip() or None
    except Exception:
        return None

SYSTEM_PROMPT = """You are Mood — a truthful, witty, maximally helpful AI assistant (Grok-style personality).
- Answer directly. Use markdown. Be concise by default, thorough when the question warrants it.
- You are excellent at coding: provide runnable code, explain briefly.
- When web search results or citations are provided, cite sources inline like [1](url).
- You have long-term memory: known user facts are provided; use them naturally, never recite the list.
Today's date: {date}"""


def sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, default=str)}\n\n"


async def get_or_create_conversation(
    db: AsyncSession,
    user: User,
    conversation_id: str | None,
    seed_text: str,
    workspace_id: str | None = None,
) -> tuple[Conversation, bool]:
    if conversation_id:
        conv = await db.get(Conversation, conversation_id)
        if not conv:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
        if conv.user_id == user.id:
            return conv, False
        if conv.workspace_id:  # shared team conversation — members may continue it
            from .workspaces import membership_of

            if await membership_of(db, conv.workspace_id, user.id):
                return conv, False
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    if workspace_id:
        from .workspaces import require_member

        await require_member(db, workspace_id, user.id)  # 403 if not a member
    conv = Conversation(user_id=user.id, title=(seed_text[:60] or "New chat"), workspace_id=workspace_id)
    db.add(conv)
    await db.flush()
    return conv, True


# Circuit breakers for context sources: once a source proves unreachable, every
# later request skips it INSTANTLY for CONTEXT_BREAKER_S seconds instead of each
# paying the 4s timeout. (Measured: dead vector store = 8s/request in pure retries.)
_breaks: dict[str, float] = {}


async def _guarded(factory, label: str, breaker: str | None = None):
    """Best-effort context source with a HARD time budget + circuit breaker.

    `factory` is a zero-arg callable returning the coroutine (so an open breaker
    never even creates it). Any source that fails or exceeds CONTEXT_BUDGET_S is
    skipped; if `breaker` is given it opens for CONTEXT_BREAKER_S on failure."""
    now = time.monotonic()
    if breaker and _breaks.get(breaker, 0) > now:
        return None  # circuit open — known-down source, zero cost
    try:
        return await asyncio.wait_for(factory(), timeout=settings.CONTEXT_BUDGET_S)
    except Exception as e:
        if breaker:
            _breaks[breaker] = now + settings.CONTEXT_BREAKER_S
        log.warning("%s failed: %s", label, e)
        return None


async def build_messages(
    db: AsyncSession,
    user: User,
    conv_id: str,
    message: str,
    file_ids: list[str],
    use_search: bool,
    created: bool = False,
) -> tuple[list[dict], str, bool]:
    """Returns (messages, model, enable_live_search). Reused by the voice pipeline."""
    persona = SYSTEM_PROMPT.format(date=date.today())
    if user.custom_instructions:
        persona += (
            "\n\nCustom instructions from the user (follow them unless they conflict "
            "with being truthful and safe):\n" + user.custom_instructions[:2000]
        )
    msgs: list[dict] = [{"role": "system", "content": persona}]

    # 1) Long-term memory + 1b) past-chat recall — CONCURRENT, each under a hard
    #    budget (they share the vector store; serialized dead-endpoint attempts
    #    were the measured ~25s first-token stall)
    mems, past = await asyncio.gather(
        _guarded(lambda: retrieve_memories(user.id, message), "memory retrieval", breaker="qdrant"),
        _guarded(lambda: retrieve_past_chats(user.id, message, exclude_conv_id=conv_id), "chat recall", breaker="qdrant"),
    )
    if mems:
        lines = "\n".join(f"- [{m.get('category', 'fact')}] {m.get('fact')}" for m in mems)
        msgs.append(
            {
                "role": "system",
                "content": "Known facts about this user (use naturally, never recite):\n" + lines,
            }
        )
    if past:
        lines = "\n".join(f'- "{c["title"]}": {c["summary"]}' for c in past)
        msgs.append(
            {
                "role": "system",
                "content": "Memories from this user's PREVIOUS conversations. When the current topic "
                "relates to one, continue it seamlessly (\"as we discussed…\"); never force them in:\n" + lines,
            }
        )

    # 1c) Brand-new conversation → digest of the most recent previous chats,
    #     so "last time we talked about…" / "continue where we left off" work directly
    if created:
        try:
            recent = await recent_chat_summaries(db, user.id, conv_id)
            if recent:
                lines = "\n".join(
                    f'- "{c.title}" ({c.updated_at.strftime("%b %d") if c.updated_at else "earlier"}): {c.summary}'
                    for c in recent
                )
                msgs.append(
                    {
                        "role": "system",
                        "content": "The user's most recent previous chats. If they reference a past "
                        "conversation (\"last time\", \"as before\", \"what did we discuss\"), use these:\n" + lines,
                    }
                )
        except Exception as e:
            log.warning("recent chats digest failed: %s", e)

    # 2) Attached files: documents as text blocks, images as vision parts
    file_blocks: list[str] = []
    image_parts: list[dict] = []
    attached_ids: set[str] = set()
    for fid in file_ids[:6]:
        asset = await db.get(FileAsset, fid)
        if not asset or asset.user_id != user.id:
            continue
        attached_ids.add(asset.id)
        if asset.mime.startswith("image/"):
            try:
                url = image_data_url(asset.path, asset.mime)
                image_parts.append({"type": "image_url", "image_url": {"url": url}})
            except Exception as e:
                log.warning("image load failed: %s", e)
        elif asset.extracted_text:
            file_blocks.append(f'<file name="{asset.filename}" type="{asset.mime}">\n{asset.extracted_text}\n</file>')

    # 2b) Doc-RAG: semantic retrieval over the rest of the user's document library
    #     (same vector store → same hard budget)
    chunks = await _guarded(lambda: retrieve_doc_chunks(user.id, message, exclude_file_ids=attached_ids), "doc retrieval", breaker="qdrant")
    if chunks:
        block = "\n\n".join(f'[doc: {c["filename"]} · relevance {c["score"]}]\n{c["text"]}' for c in chunks)
        msgs.append(
            {
                "role": "system",
                "content": "Relevant excerpts from the user's documents (reference the filename when using them):\n"
                + block,
            }
        )

    # 3) Tavily alternative search path (xAI Live Search is the default)
    if use_search and settings.SEARCH_PROVIDER == "tavily":
        ctx = await tavily_context(message)
        if ctx:
            msgs.append({"role": "system", "content": "Fresh web results — cite with [n](url):\n" + ctx})

    # 4) Recent history (sliding window)
    rows = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at.desc())
            .limit(settings.HISTORY_WINDOW)
        )
    ).scalars().all()
    for m in reversed(rows):
        if m.role in ("user", "assistant"):
            msgs.append({"role": m.role, "content": m.content})

    # 5) The new user message (+ files/images)
    text = message
    if file_blocks:
        text = "\n\n".join(file_blocks) + "\n\n" + message
    content = [{"type": "text", "text": text}] + image_parts if image_parts else text
    msgs.append({"role": "user", "content": content})

    model = settings.MODEL_VISION if image_parts else settings.MODEL_CHAT
    enable_live_search = use_search and settings.SEARCH_PROVIDER == "xai_live"
    return msgs, model, enable_live_search


async def generate_title(conv_id: str, first_msg: str) -> None:
    # Quota economy: on the stand-in stack (LLM_FALLBACK_PROVIDER) the shared key
    # may be on a tiny daily budget — the seeded title (first words of the chat,
    # set at conversation creation) is kept and the LLM prettifier is skipped.
    if (settings.LLM_FALLBACK_PROVIDER or "").strip():
        return
    try:
        title = (
            await llm.complete(
                [
                    {
                        "role": "user",
                        "content": f"Give a short 3-6 word conversation title (no quotes) for a chat starting with:\n{first_msg[:300]}",
                    }
                ],
                max_tokens=20,
            )
        ).strip()
        async with SessionLocal() as s:
            c = await s.get(Conversation, conv_id)
            if c and title:
                c.title = title[:80]
                await s.commit()
    except Exception as e:
        log.warning("title generation failed: %s", e)


@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    bg: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not req.message.strip() and not req.files and not req.regenerate:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty message")
    await enforce_rate_limit(f"chat:{user.id}", settings.CHAT_RATE_LIMIT_PER_MIN * plan_rate_mult(user.plan))

    # Regenerate: replay the last user message (delete previous exchange, resend cleanly)
    if req.regenerate:
        if not req.conversation_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to regenerate")
        conv = await db.get(Conversation, req.conversation_id)
        if not conv or conv.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
        last_two = (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.created_at.desc())
                .limit(2)
            )
        ).scalars().all()
        user_text = None
        for m in last_two:
            if m.role == "user" and user_text is None:
                user_text = m.content
            await db.delete(m)
        if not user_text:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to regenerate")
        req.message = user_text
        req.files = []

    conv, created = await get_or_create_conversation(
        db, user, req.conversation_id, req.message, req.workspace_id
    )
    db.add(
        Message(conversation_id=conv.id, user_id=user.id, role="user", content=req.message, meta={"files": req.files})
    )
    for fid in req.files[:6]:  # link assets to the conversation
        a = await db.get(FileAsset, fid)
        if a and a.user_id == user.id:
            a.conversation_id = conv.id
    await db.commit()

    messages, model, live_search = await build_messages(
        db, user, conv.id, req.message, req.files, req.search, created
    )
    # 🚀 Premium picker: honor the requested model (vision threads stay on the vision model).
    if model != settings.MODEL_VISION and req.model in MODEL_CHOICES:
        model = MODEL_CHOICES[req.model]
    # 🧠 Extended reasoning: stream live traces for think-capable models.
    think_on = bool(req.think) and model in THINKABLE_MODELS

    # Plugins: act on connected apps first (writes become pending approvals); inject results
    tool_calls: list[dict] = []
    pending_actions: list[dict] = []
    if req.plugins and not req.regenerate:
        try:
            tool_ctx, tool_calls, pending_actions = await resolve_plugins(db, user, req.message, conv.id)
            if tool_ctx:
                messages.insert(1, {"role": "system", "content": tool_ctx})
        except Exception as e:
            log.warning("plugin resolution failed: %s", e)

    async def event_source():
        full: list[str] = []
        usage: dict = {}
        traces: list[str] = []
        think_t0 = time.perf_counter()
        try:
            yield sse({"type": "meta", "conversation_id": conv.id, "model": model, "created": created})
            if tool_calls:
                yield sse({"type": "tools", "calls": tool_calls})
            if pending_actions:
                yield sse({"type": "confirm", "actions": pending_actions})
            if think_on:
                yield sse({"type": "thinking_start", "provider": "xai"})
            async for ev in llm.stream_chat(messages, model=model, enable_search=live_search, think=think_on):
                if ev["type"] == "reasoning":
                    traces.append(ev["text"])
                    yield sse({"type": "thinking_trace", "trace": ev["text"][-600:]})
                    continue
                if ev["type"] == "delta":
                    full.append(ev["text"])
                if ev["type"] == "usage":
                    usage = ev.get("usage") or {}  # metered below; not forwarded on the wire
                    continue
                yield sse(ev)
            reply = "".join(full) or "(no response)"

            # 🧠 Finalize thinking: persisted meta matches the client's reload contract
            think_meta: dict | None = None
            if think_on:
                elapsed = int((time.perf_counter() - think_t0) * 1000)
                summary = await summarize_thinking("".join(traces))
                think_meta = {
                    "mode": "chat+think",
                    "provider": "xai",
                    "think_traces": [t[-600:] for t in traces[-settings.THINK_TRACE_KEEP:]],
                    "thinking_summary": summary,
                    "think_time_ms": elapsed,
                    "think_usage": (
                        {model: {"in": int(usage.get("prompt_tokens", 0)), "out": int(usage.get("completion_tokens", 0))}}
                        if usage
                        else None
                    ),
                }
                yield sse({"type": "thinking", "thinking": {"summary": summary}, "think_time_ms": elapsed})

            async with SessionLocal() as s:
                s.add(Message(conversation_id=conv.id, role="assistant", content=reply, meta=think_meta or {}))
                c = await s.get(Conversation, conv.id)
                if c:
                    c.updated_at = datetime.now(timezone.utc)
                await s.commit()
            tok = (
                {
                    "tokens_in": int(usage.get("prompt_tokens", 0)),
                    "tokens_out": int(usage.get("completion_tokens", 0)),
                    "estimated": False,
                }
                if usage
                else estimate_tokens(req.message + json.dumps(messages[0])[:3000], reply)
            )
            await record_usage(user.id, "chat", model, **tok)
            bg.add_task(extract_and_store, user.id, req.message, reply, user.plan)
            bg.add_task(update_conversation_summary, user.id, conv.id)
            if created:
                bg.add_task(generate_title, conv.id, req.message)
            yield sse({"type": "done"})
        except Exception as e:
            log.exception("chat stream failed")
            yield sse({"type": "error", "message": friendly_ai_error(e)})

    return StreamingResponse(
        track_stream(event_source()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/image")
async def generate_image(req: ImageRequest, user: User = Depends(get_current_user)):
    await enforce_rate_limit(f"img:{user.id}", 10 * plan_rate_mult(user.plan))
    try:
        url = await llm.generate_image(req.prompt)
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, friendly_ai_error(e))
    if not url:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Image provider returned no image")
    await record_usage(user.id, "image", settings.MODEL_IMAGE)
    return {"url": url, "prompt": req.prompt}
