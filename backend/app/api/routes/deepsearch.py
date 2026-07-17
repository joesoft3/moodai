"""DeepSearch SSE endpoint — multi-round agentic research with citations.

Event stream:
  meta → subtopics → [round_start → query_start×N → query_done×N → (reflect)]×rounds
       → writing → delta×N → done | error
"""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.metrics import track_stream
from ...db.models import Conversation, Message, User
from ...db.session import SessionLocal, get_db
from ...schemas import ChatRequest
from ...services.deepsearch import (
    build_synthesis_messages,
    decompose,
    depth_config,
    gap_analysis,
    research_query,
)
from ...services.llm import friendly_ai_error, llm
from ...services.memory import extract_and_store
from ...services.metering import estimate_tokens, plan_rate_mult, record_usage
from ...services.recall import update_conversation_summary
from ..deps import enforce_rate_limit, get_current_user
from .chat import generate_title, get_or_create_conversation, sse

router = APIRouter()
log = logging.getLogger(__name__)

MAX_SOURCES = 40


@router.post("/stream")
async def deepsearch_stream(
    req: ChatRequest,
    bg: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not req.message.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty question")
    await enforce_rate_limit(f"deep:{user.id}", 8 * plan_rate_mult(user.plan))

    conv, created = await get_or_create_conversation(db, user, req.conversation_id, "🔭 " + req.message)
    db.add(Message(conversation_id=conv.id, role="user", content=req.message, meta={"mode": "deepsearch", "depth": req.depth}))
    await db.commit()

    rounds, n_questions = depth_config(req.depth)

    async def event_source():
        try:
            yield sse({"type": "meta", "conversation_id": conv.id, "model": f"deepsearch-{req.depth}", "created": created})

            # 1) Plan the research
            questions = await decompose(req.message, n_questions)
            yield sse({"type": "subtopics", "subtopics": questions})

            findings: list[tuple[str, str]] = []   # (question, findings_text)
            sources: list[str] = []                # ordered unique citations
            queue: list[str] = questions

            # 2) Research rounds with gap analysis between them
            for r in range(1, rounds + 1):
                if not queue:
                    break
                yield sse({"type": "round_start", "round": r, "total": rounds})

                # research this round's questions concurrently
                tasks: dict[asyncio.Task, str] = {}
                for q in queue:
                    yield sse({"type": "query_start", "query": q})
                    tasks[asyncio.create_task(research_query(q))] = q

                for fut in asyncio.as_completed(tasks):
                    q = tasks[fut]
                    try:
                        text, cites = await fut
                    except Exception as e:
                        text, cites = f"(research failed: {e})", []
                    if cites:
                        for u in cites:
                            if u not in sources and len(sources) < MAX_SOURCES:
                                sources.append(u)
                    findings.append((q, text))
                    yield sse({"type": "query_done", "query": q, "sources": len(cites)})

                yield sse({"type": "round_done", "round": r, "sources": len(sources)})

                # 3) Gap analysis → next round's follow-ups
                if r < rounds:
                    note, followups = await gap_analysis(req.message, findings, n_questions)
                    if note:
                        yield sse({"type": "reflect", "note": note})
                    queue = [f for f in followups if f not in [q for q, _ in findings]]
                    if not queue:
                        yield sse({"type": "reflect", "note": "Coverage is sufficient — moving to writing."})
                        break

            # 4) Synthesize the report (real token streaming)
            yield sse({"type": "writing"})
            messages = build_synthesis_messages(req.message, findings, sources)
            full: list[str] = []
            try:
                async for ev in llm.stream_chat(messages, model=settings.MODEL_CHAT):
                    if ev["type"] == "delta":
                        full.append(ev["text"])
                        yield sse(ev)
            except Exception as e:
                yield sse({"type": "error", "message": friendly_ai_error(e)})
                return

            answer = "".join(full) or "(no report produced)"
            if sources and "**Sources**" not in answer:
                suffix = "\n\n**Sources**\n" + "\n".join(f"- [{i+1}]({u})" for i, u in enumerate(sources))
                answer += suffix
                yield sse({"type": "delta", "text": suffix})

            # 5) Persist + background memory/title
            async with SessionLocal() as s:
                s.add(
                    Message(
                        conversation_id=conv.id,
                        role="assistant",
                        content=answer,
                        meta={"mode": "deepsearch", "questions": [q for q, _ in findings], "sources": len(sources)},
                    )
                )
                c = await s.get(Conversation, conv.id)
                if c:
                    c.updated_at = datetime.now(timezone.utc)
                await s.commit()
            await record_usage(user.id, "deepsearch", settings.MODEL_CHAT, **estimate_tokens(req.message, answer))
            bg.add_task(extract_and_store, user.id, req.message, answer, user.plan)
            bg.add_task(update_conversation_summary, user.id, conv.id)
            if created:
                bg.add_task(generate_title, conv.id, req.message)
            yield sse({"type": "done"})
        except Exception as e:
            log.exception("deepsearch failed")
            yield sse({"type": "error", "message": friendly_ai_error(e)})

    return StreamingResponse(
        track_stream(event_source()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
