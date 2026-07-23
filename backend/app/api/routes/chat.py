"""Streaming chat orchestrator: auth → context assembly (memory + files + search)
→ model routing → SSE stream → background memory extraction & titling.
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import date, datetime, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.metrics import track_stream
from ...db.models import Conversation, FileAsset, Message, User
from ...db.session import SessionLocal, get_db
from ...schemas import ChatRequest, ImageRequest
from ...services.create_intent import CreateIntent, route_media_intent
from ...services.file_extract import image_data_url
from ...services.llm import friendly_ai_error, llm
from ...services.media import VideoGenerationError, VideoNotConfigured, VideoOptions, video
from ...services.memory import extract_and_store, retrieve_memories
from ...services.metering import PLAN_LIMITS, count_today, estimate_tokens, plan_rate_mult, record_usage
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


def _ctx_budget() -> float:
    """Budget for a context source. pgvector lives in the SAME Postgres the chat
    already can't run without (same-fate store) — a tight budget there only penalizes
    Neon compute wake-from-idle (measured live: first post-wake query ≈ 4-8s → false
    breaker trips). External Qdrant keeps the original tight budget (it's truly optional)."""
    budget = settings.CONTEXT_BUDGET_S
    try:
        from ...services.vectorstore import pgvector_active

        if pgvector_active():
            return max(budget, 8.0)
    except Exception:
        pass
    return budget


async def _guarded(factory, label: str, breaker: str | None = None):
    """Best-effort context source with a HARD time budget + circuit breaker.

    `factory` is a zero-arg callable returning the coroutine (so an open breaker
    never even creates it). Any source that fails or exceeds the budget is
    skipped; if `breaker` is given it opens for CONTEXT_BREAKER_S on failure."""
    now = time.monotonic()
    if breaker and _breaks.get(breaker, 0) > now:
        return None  # circuit open — known-down source, zero cost
    try:
        return await asyncio.wait_for(factory(), timeout=_ctx_budget())
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
    # Quota economy (QUOTA_ECONOMY=1): keep the seeded first-words title and skip the
    # LLM prettifier as a daily-budget shield. Off by default — pretty titles stay live.
    if settings.QUOTA_ECONOMY:
        return
    try:
        title = (
            await llm.complete(
                [
                    {
                        "role": "user",
                        "content": (
                            "Write a short 3-6 word title naming the TOPIC of this chat "
                            "(plain words, no quotes):\n" + first_msg[:300]
                        ),
                    }
                ],
                max_tokens=32,
            )
        ).strip().strip('"').strip()
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

    # 🎨🎬 In-chat creation (v1.9.7) — "create an image of…" / "make a video of…"
    # Routed BEFORE context assembly: zero LLM classification cost, no memory/RAG
    # retrieval spent on gen prompts, generation streams inline like ChatGPT.
    # NOTE: the web/mobile composers ship search=true by default — the media
    # intent must win over that (a creation turn never needs web context).
    if settings.CHAT_MEDIA and not req.files and not req.plugins:
        last_media: dict | None = None
        if not created:
            prev = (
                await db.execute(
                    select(Message)
                    .where(Message.conversation_id == conv.id, Message.role == "assistant")
                    .order_by(Message.created_at.desc())
                    .limit(1)
                )
            ).scalars().first()
            if prev and isinstance(prev.meta, dict):
                ml = prev.meta.get("media")
                if isinstance(ml, list) and ml and isinstance(ml[0], dict):
                    last_media = ml[0]
        intent: CreateIntent | None = None
        if req.mode in ("image", "video") and req.message.strip():
            intent = CreateIntent(kind=req.mode, prompt=req.message.strip())
        else:
            intent = route_media_intent(req.message, last_media)
        if intent:
            return await _media_stream(req, db, user, conv, created, intent, bg)

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


async def _persist_generated_media(db: AsyncSession, user: User, url: str, expect: str) -> tuple[str, str]:
    """Archive generated media (image|video): download the bytes → durable storage
    (R2/local) → FileAsset row so it lives in the user's library. Returns
    (render_url, stored_kind) — falls back to the provider link on ANY hiccup
    (a generation never fails because archiving did)."""
    if not settings.IMAGE_PERSIST:
        return url, "hotlink"
    max_mb = settings.MAX_UPLOAD_MB if expect == "image" else settings.VIDEO_MAX_DOWNLOAD_MB
    exts = (
        {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}
        if expect == "image"
        else {"video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov"}
    )
    try:
        import base64

        from ...services import storage

        if url.startswith("data:"):
            head, _, b64 = url.partition(",")
            mime = (head[5:].split(";")[0] or f"{expect}/png").strip()
            data = base64.b64decode(b64)
        elif "/api/v1/media/files/" in url:
            # Self-hosted composer output (reel/pollinations clips): read straight
            # from this machine's MEDIA_DIR — a loopback GET can land on a SIBLING
            # Fly machine that never wrote the file (measured live: 404 → hotlink,
            # dead link after the 24h janitor). Local read is always correct.
            import os
            import re as _re

            name = url.rsplit("/", 1)[-1]
            if not _re.fullmatch(r"[A-Za-z0-9._-]+", name or ""):
                raise ValueError("bad media name")
            local = os.path.join(settings.MEDIA_DIR, name)
            with open(local, "rb") as fh:
                data = fh.read()
            mime = "video/mp4" if name.endswith(".mp4") else ("image/jpeg" if name.endswith((".jpg", ".jpeg")) else f"{expect}/mp4")
        else:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, read=120.0), follow_redirects=True) as client:
                r = await client.get(url)
                r.raise_for_status()
                mime = (r.headers.get("content-type") or ("image/jpeg" if expect == "image" else "video/mp4")).split(";")[0].strip()
                data = r.content
        if not data or not mime.startswith(f"{expect}/") or len(data) > max_mb * 1024 * 1024:
            return url, "hotlink"
        ext = exts.get(mime, "jpg" if expect == "image" else "mp4")
        fname = f"mood-gen-{uuid.uuid4().hex[:12]}.{ext}"
        marker = await storage.put_upload(user.id, fname, data)
        db.add(FileAsset(user_id=user.id, filename=fname, mime=mime, path=marker, size_bytes=len(data)))
        await db.commit()
        fresh = await storage.presigned_url(marker, settings.IMAGE_PERSIST_TTL_S)
        return (fresh or url), ("r2" if storage.is_remote(marker) else "local")
    except Exception as e:
        log.warning("%s persistence skipped (serving provider link): %s", expect, e)
        return url, "hotlink"


async def _persist_generated_image(db: AsyncSession, user: User, url: str) -> tuple[str, str]:
    return await _persist_generated_media(db, user, url, "image")


def _video_opts_from_prompt(prompt: str) -> VideoOptions:
    """Free aspect/style hints picked out of natural language (no LLM)."""
    p = prompt.lower()
    aspect = "9:16" if any(w in p for w in ("vertical", "portrait", "tall ", "phone", "tiktok", "reel")) else "16:9"
    if "square" in p:
        aspect = "1:1"
    style = "cinematic"
    for w, s in (("anime", "anime"), ("photoreal", "photoreal"), ("photo-real", "photoreal"),
                 ("timelapse", "timelapse"), ("time-lapse", "timelapse"), ("documentary", "documentary"),
                 ("retro", "retro_film"), ("16mm", "retro_film"), ("product ad", "product_ad"),
                 ("commercial", "product_ad")):
        if w in p:
            style = s
            break
    return VideoOptions(duration=8, aspect_ratio=aspect, quality="720p", style=style)


async def _media_stream(
    req: ChatRequest,
    db: AsyncSession,
    user: User,
    conv: Conversation,
    created: bool,
    intent: CreateIntent,
    bg: BackgroundTasks,
) -> StreamingResponse:
    """🎨🎬 One SSE contract for in-chat creations: meta → media_start →
    (media_progress…) → media → done. The assistant message persists with
    meta.media so web + mobile re-render the artifact on reload."""
    kind = intent.kind
    prompt = intent.prompt[:900]
    if kind == "image":
        await enforce_rate_limit(
            f"chatimg:{user.id}", settings.CHAT_IMAGE_RATE_PER_MIN * plan_rate_mult(user.plan)
        )
    else:
        await enforce_rate_limit(
            f"chatvid:{user.id}", settings.CHAT_VIDEO_RATE_PER_MIN * plan_rate_mult(user.plan)
        )
        cap = PLAN_LIMITS.get(user.plan, PLAN_LIMITS["free"]).get("video_day", 0)
        if cap and await count_today(db, user.id, "video") >= cap:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Daily video limit reached for the {user.plan} plan ({cap}/day). Upgrade for more.",
            )

    async def event_source():
        model_label = "Mood Canvas" if kind == "image" else "Mood Reel"
        try:
            yield sse({"type": "meta", "conversation_id": conv.id, "model": model_label, "created": created})
            yield sse({"type": "media_start", "kind": kind, "prompt": prompt})
            if kind == "image":
                url = await llm.generate_image(prompt)
                if not url:
                    raise VideoGenerationError("Image provider returned no image")
                async with SessionLocal() as ps:  # fresh session — request db may be closed mid-stream
                    render_url, stored = await _persist_generated_image(ps, user, url)
            else:
                q: asyncio.Queue = asyncio.Queue()

                async def run_video() -> None:
                    try:
                        # aspect/style hints live in the raw instruction; prompt is the cleaned idea
                        u, _ = await video.generate(
                            prompt, _video_opts_from_prompt(f"{req.message} {prompt}"),
                            on_progress=lambda d: q.put_nowait(d),
                        )
                        await q.put({"type": "result", "url": u})
                    except Exception as e:  # noqa: BLE001 - delivered on the wire, not raised
                        await q.put({"type": "fail", "err": e})

                task = asyncio.create_task(run_video())
                try:
                    provider_url = None
                    while True:
                        item = await asyncio.wait_for(q.get(), timeout=settings.VIDEO_MAX_WAIT_SECONDS)
                        if item.get("type") == "result":
                            provider_url = item["url"]
                            break
                        if item.get("type") == "fail":
                            raise item["err"]
                        yield sse(
                            {
                                "type": "media_progress",
                                "kind": kind,
                                "stage": item.get("stage"),
                                "done": item.get("done"),
                                "total": item.get("total"),
                            }
                        )
                finally:
                    if not task.done():
                        task.cancel()
                async with SessionLocal() as ps:  # fresh session — request db may be closed mid-stream
                    render_url, stored = await _persist_generated_media(ps, user, provider_url, "video")

            media_obj = {"kind": kind, "url": render_url, "prompt": prompt, "stored": stored}
            if intent.refine:
                caption = (
                    f"🎨 **Remixed it** — *\"{prompt}\"*" if kind == "image"
                    else f"🎬 **Re-cut your reel** — *\"{prompt}\"*"
                )
            else:
                caption = (
                    f"🎨 **Here's your image** — *\"{prompt}\"*" if kind == "image"
                    else f"🎬 **Your reel is ready** — *\"{prompt}\"*"
                )
            caption += "\n\n_Say “make it …” to iterate — it’s also saved to your Files library._"
            yield sse({"type": "media", **media_obj})
            yield sse({"type": "delta", "text": caption})  # live caption == persisted content
            async with SessionLocal() as s:
                s.add(
                    Message(
                        conversation_id=conv.id,
                        role="assistant",
                        content=caption,
                        meta={"mode": "media", "media": [media_obj]},
                    )
                )
                c = await s.get(Conversation, conv.id)
                if c:
                    c.updated_at = datetime.now(timezone.utc)
                await s.commit()
            await record_usage(
                user.id,
                kind,
                settings.MODEL_IMAGE if kind == "image" else settings.MODEL_VIDEO,
            )
            # gen prompts aren't user facts — skip memory extraction (quota + hygiene);
            # the conversation still gets titled + summarized like any other.
            if created:
                bg.add_task(generate_title, conv.id, req.message)
            bg.add_task(update_conversation_summary, user.id, conv.id)
            yield sse({"type": "done"})
        except Exception as e:
            log.warning("in-chat %s failed: %s", kind, e)
            if isinstance(e, VideoNotConfigured):
                msg = f"{e}"
            elif isinstance(e, VideoGenerationError):
                msg = f"Couldn’t finish that {kind} — {e}"
            else:
                msg = (
                    f"Couldn’t finish that {kind} — the creation studio hiccuped on my end. "
                    "Try again in a moment."
                )
            yield sse({"type": "error", "message": msg})

    return StreamingResponse(
        track_stream(event_source()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/image")
async def generate_image(
    req: ImageRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await enforce_rate_limit(f"img:{user.id}", 10 * plan_rate_mult(user.plan))
    try:
        url = await llm.generate_image(req.prompt)
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, friendly_ai_error(e))
    if not url:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Image provider returned no image")
    render_url, stored = await _persist_generated_image(db, user, url)
    await record_usage(user.id, "image", settings.MODEL_IMAGE)
    return {"url": render_url, "prompt": req.prompt, "stored": stored, "source_url": url}
