"""Multi-agent SSE endpoint.

Event stream: meta → plan → (step_start → step_done)×N → delta×N → done | error
The client renders the plan and per-step progress above the final answer.
"""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.metrics import track_stream
from ...db.models import Conversation, Message, User
from ...db.session import SessionLocal, get_db
from ...schemas import ChatRequest
from ...services.agents import critic_review, plan, run_agent
from ...services.llm import friendly_ai_error
from ...services.memory import extract_and_store
from ...services.metering import add_tokens, estimate_tokens, plan_rate_mult, record_usage
from ...services.notify import notify_arena_done
from ...services.recall import update_conversation_summary
from ..deps import enforce_rate_limit, get_current_user
from .chat import generate_title, get_or_create_conversation, sse

router = APIRouter()
log = logging.getLogger(__name__)


@router.post("/stream")
async def agent_stream(
    req: ChatRequest,
    bg: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not req.message.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty goal")
    await enforce_rate_limit(f"agent:{user.id}", 10 * plan_rate_mult(user.plan))

    conv, created = await get_or_create_conversation(db, user, req.conversation_id, "🤖 " + req.message)
    db.add(Message(conversation_id=conv.id, role="user", content=req.message, meta={"mode": "agent"}))
    await db.commit()

    async def event_source():
        try:
            yield sse({"type": "meta", "conversation_id": conv.id, "model": "multi-agent", "created": created})

            # 1) Plan (planner only picks researcher/coder/writer; the critic is added by us)
            steps = (await plan(req.message))[:4]
            if not steps or steps[-1]["agent"] != "writer":
                steps.append(
                    {"agent": "writer", "task": "Synthesize the team's findings into a complete, polished answer."}
                )
            steps.append({"agent": "critic", "task": "Fact-check, fill gaps and polish the final answer."})
            yield sse({"type": "plan", "steps": steps})

            workers, synth = steps[:-2], steps[-2]  # critic is steps[-1]
            totals: dict = {}
            citations: list[str] = []
            prior: list[tuple[str, str, str]] = []

            # 2) Specialist agents run CONCURRENTLY (they only need the goal, not each other)
            async def _work(i: int, step: dict):
                u: dict = {}
                try:
                    out, cites = await run_agent(step["agent"], step["task"], req.message, [], usage_out=u)
                except Exception as e:
                    out, cites, u = f"({step['agent']} failed: {e})", [], {}
                return i, step, out, cites, u

            running = [asyncio.create_task(_work(i, st)) for i, st in enumerate(workers)]
            for i, st in enumerate(workers):
                yield sse({"type": "step_start", "i": i, "agent": st["agent"], "task": st["task"]})
            for fut in asyncio.as_completed(running):
                i, step, output, cites, u = await fut
                add_tokens(totals, u)
                prior.append((step["agent"], step["task"], output))
                citations += cites
                yield sse({"type": "step_done", "i": i, "agent": step["agent"], "task": step["task"], "preview": output[:280]})

            # 3) Writer synthesizes (sees all worker outputs) → 4) Critic reviews & fixes
            wi = len(workers)
            yield sse({"type": "step_start", "i": wi, "agent": "writer", "task": synth["task"]})
            try:
                u: dict = {}
                draft, w_cites = await run_agent("writer", synth["task"], req.message, prior, usage_out=u)
                add_tokens(totals, u)
                citations += w_cites
            except Exception as e:
                yield sse({"type": "error", "message": friendly_ai_error(e)})
                return
            yield sse({"type": "step_done", "i": wi, "agent": "writer", "task": synth["task"], "preview": draft[:280]})

            ci = wi + 1
            yield sse({"type": "step_start", "i": ci, "agent": "critic", "task": steps[-1]["task"]})
            try:
                u = {}
                answer = await critic_review(req.message, draft, prior, usage_out=u)
                add_tokens(totals, u)
                if not answer.strip():
                    answer = draft
            except Exception as e:
                log.warning("critic failed, using writer draft: %s", e)
                answer = draft
            yield sse({"type": "step_done", "i": ci, "agent": "critic", "task": steps[-1]["task"], "preview": answer[:280]})

            if citations:
                uniq = list(dict.fromkeys(citations))
                answer += "\n\n**Sources**\n" + "\n".join(f"- [{i+1}]({u})" for i, u in enumerate(uniq))

            # 4) Stream the answer to the client (chunked for a live feel)
            for i in range(0, len(answer), 48):
                yield sse({"type": "delta", "text": answer[i : i + 48]})
                await asyncio.sleep(0.01)

            # 5) Persist + background memory/title
            async with SessionLocal() as s:
                s.add(
                    Message(
                        conversation_id=conv.id,
                        role="assistant",
                        content=answer,
                        meta={"mode": "agent", "agents": [st["agent"] for st in steps]},
                    )
                )
                c = await s.get(Conversation, conv.id)
                if c:
                    c.updated_at = datetime.now(timezone.utc)
                await s.commit()
            tok = (
                {"tokens_in": totals.get("tokens_in", 0), "tokens_out": totals.get("tokens_out", 0), "estimated": False}
                if totals
                else estimate_tokens(req.message, answer)
            )
            await record_usage(user.id, "agent", settings.MODEL_CHAT, **tok)
            bg.add_task(extract_and_store, user.id, req.message, answer, user.plan)
            bg.add_task(update_conversation_summary, user.id, conv.id)
            if created:
                bg.add_task(generate_title, conv.id, req.message)
            yield sse({"type": "done"})
        except Exception as e:
            log.exception("agent run failed")
            yield sse({"type": "error", "message": friendly_ai_error(e)})

    return StreamingResponse(
        track_stream(event_source()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# ⚔️ Arena (Pro feature) — multi-provider drafts → blind ballots → Grok-4 verdict
# ---------------------------------------------------------------------------

@router.post("/arena/stream")
async def arena_stream(
    req: ChatRequest,
    bg: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not req.message.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty question")
    await enforce_rate_limit(f"arena:{user.id}", 8 * plan_rate_mult(user.plan))

    # Plan gate: free users get a small daily teaser; Pro gets the full panel.
    from ...services.metering import PLAN_LIMITS, count_today

    limits = PLAN_LIMITS.get(user.plan, PLAN_LIMITS["free"])
    cap = limits.get("arena_day", 0)

    # 🌐 White-label: an active custom domain can re-brand the arena, pick the
    # judge/panel and tighten the per-user daily cap (never loosens the plan cap).
    from ...db.models import Domain
    from ...services.arena import ArenaConfig
    from ...services.domains import clean_domain

    from sqlalchemy import select as sa_select

    arena_cfg: ArenaConfig | None = None
    try:
        host = request.headers.get("x-mood-host", "")
        dname = clean_domain(host.split(":")[0]) if host else ""
    except Exception:
        dname = ""
    dom: Domain | None = None
    if dname:
        dom = await db.scalar(sa_select(Domain).where(Domain.domain == dname, Domain.status == "active"))
    if dom and dom.arena_enabled:
        arena_cfg = ArenaConfig(
            brand=dom.arena_brand or dom.brand_name or dom.domain,
            judge_model=dom.arena_judge,
            judge_persona=dom.arena_brand or dom.brand_name,
            panel=dom.arena_panel,
        )
        if dom.arena_daily_cap:
            cap = min(cap, dom.arena_daily_cap) if cap else dom.arena_daily_cap
    if cap and await count_today(db, user.id, "arena") >= cap:
        async def upgrade_source():
            yield sse({
                "type": "error",
                "error_code": "plan_limit",
                "message": (
                    f"⚔️ Arena limit reached — the {user.plan} plan includes {cap} debate"
                    f"{'s' if cap != 1 else ''}/day. Upgrade to Pro for "
                    f"{PLAN_LIMITS['pro'].get('arena_day', 100)}/day, drafts from every "
                    "configured provider and Grok-4 verdicts."
                ),
            })

        return StreamingResponse(
            upgrade_source(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    conv, created = await get_or_create_conversation(db, user, req.conversation_id, "⚔️ " + req.message)
    db.add(Message(conversation_id=conv.id, role="user", content=req.message, meta={"mode": "arena"}))
    await db.commit()

    from ...services.arena import run_arena

    # ⚔️ Rematch: drafters try to beat the previous arena winner in this conversation
    prior_winner: str | None = None
    if req.rematch:
        from sqlalchemy import select

        res = await db.execute(
            select(Message.content)
            .where(
                Message.conversation_id == conv.id,
                Message.role == "assistant",
                Message.meta["mode"].astext == "arena",
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        prior_winner = res.scalar_one_or_none()

    async def event_source():
        content, meta = "", {}
        try:
            yield sse({"type": "meta", "conversation_id": conv.id, "model": "arena", "created": created})
            async for ev in run_arena(req.message, req.arena_extra, prior_winner=prior_winner, cfg=arena_cfg):
                if ev["type"] == "delta":
                    content += ev["text"]
                elif ev["type"] == "arena_verdict":
                    meta = {
                        "mode": "arena",
                        "winner": ev["winner"],
                        "judge": ev.get("judge"),
                        "brand": ev.get("brand"),
                        "draft_order": ev["draft_order"],
                        "drafts": ev["drafts"],
                        "votes": ev["votes"],
                        "scores": ev.get("scores", {}),
                        "usage": ev["usage"],
                    }
                yield sse(ev)

            # Persist + meter
            async with SessionLocal() as s:
                if content:
                    s.add(Message(conversation_id=conv.id, role="assistant", content=content, meta=meta or {"mode": "arena"}))
                c = await s.get(Conversation, conv.id)
                if c:
                    c.updated_at = datetime.now(timezone.utc)
                await s.commit()
            totals = {"in": 0, "out": 0}
            for u in (meta.get("usage") or {}).values():
                totals["in"] += int(u.get("in", 0))
                totals["out"] += int(u.get("out", 0))
            if totals["in"] or totals["out"]:
                await record_usage(
                    user.id, "arena", settings.ARENA_XAI_MODEL or settings.MODEL_CHAT,
                    tokens_in=totals["in"], tokens_out=totals["out"], estimated=False,
                )
            else:
                await record_usage(user.id, "arena", settings.MODEL_CHAT, **estimate_tokens(req.message, content))
            bg.add_task(extract_and_store, user.id, req.message, content, user.plan)
            bg.add_task(update_conversation_summary, user.id, conv.id)
            if created:
                bg.add_task(generate_title, conv.id, req.message)
            if meta:  # push: "⚔️ Arena verdict in" — no-op unless FCM env set
                notify_arena_done(user.id, str(meta.get("winner") or ""))
        except Exception as e:
            log.exception("arena failed")
            yield sse({"type": "error", "message": friendly_ai_error(e)})

    return StreamingResponse(
        track_stream(event_source()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
