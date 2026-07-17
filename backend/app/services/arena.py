"""⚔️ Multi-model arena — the Pro feature.

Several configured providers draft answers to the same question in parallel,
then every panelist blindly votes on the anonymized drafts, and Grok-4 (xAI)
delivers the final verdict. The winning draft is streamed as the answer.

Panel (env-tunable models):
  • xAI   — ARENA_XAI_MODEL   (default MODEL_CHAT, e.g. grok-4)   [judge too]
  • OpenAI  — ARENA_OPENAI_MODEL (default gpt-4o)
  • Gemini  — ARENA_GEMINI_MODEL (default gemini-2.5-pro)
Providers without an API key are skipped (with a `warning` event); a one-provider
"arena" degrades gracefully into a normal single-model answer.

SSE events yielded: topic → warning* → draft_start/draft_done×N →
vote_cast×N → arena_verdict → delta×N (winning draft) → usage → done.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from typing import Any, AsyncIterator

from ..config import settings
from .llm import friendly_ai_error, llm

log = logging.getLogger(__name__)

def _xai_model() -> str:
    """Judge/draft model for xAI — ARENA_XAI_MODEL may be "" → default MODEL_CHAT."""
    return settings.ARENA_XAI_MODEL or settings.MODEL_CHAT


DRAFT_SYSTEM = (
    "You are a contestant in a blind multi-model answer arena judged by a panel. "
    "Answer the user's question directly, accurately and concretely in under 350 words. "
    "No meta-commentary about the competition — just your best answer."
)

VOTE_SYSTEM = (
    "You are judging anonymized answers A/B/C to a user question. "
    "Pick the SINGLE best answer for correctness, completeness and clarity. "
    'Reply with ONLY compact JSON: {"vote": "A", "rationale": "one short sentence"}.'
)

JUDGE_SYSTEM = (
    "You are Grok-4, the final judge of a blind multi-model arena. You receive the "
    "question, the anonymized drafts and the panel's ballots. Score every draft and "
    'reply with ONLY compact JSON: {"winner": "A", "reason": "one short sentence", '
    '"scores": {"A": {"accuracy": 8, "clarity": 9}, "B": {"accuracy": 7, "clarity": 8}}}'
    " — winner is the letter of the best draft; scores are integers 1–10."
)


def _judge_system(cfg: "ArenaConfig | None") -> str:
    """White-label domains can swap the judge persona (the wiring stays Grok-4 underneath)."""
    if cfg and cfg.judge_persona:
        return JUDGE_SYSTEM.replace("You are Grok-4", f"You are {cfg.judge_persona}")
    return JUDGE_SYSTEM


class ArenaConfig:
    """Per-domain arena overrides (white-label). Everything optional; None → platform default."""

    def __init__(
        self,
        brand: str | None = None,
        judge_model: str | None = None,
        judge_persona: str | None = None,
        panel: list[dict[str, str]] | None = None,
    ) -> None:
        self.brand = brand
        self.judge_model = judge_model
        self.judge_persona = judge_persona
        self.panel = panel  # list of {"provider","model","label"} — must still have API keys

REMATCH_NOTE = (
    "\n\nREMATCH: a previous arena round produced this winning answer — try to BEAT it "
    "(correct it where weak, add what it missed, say it better):\n\"\"\"\n{prior}\n\"\"\""
)


def _panel(extra: str | None, cfg: "ArenaConfig | None" = None) -> list[dict[str, str]]:
    """Provider/model contestants that actually have API keys."""
    if cfg and cfg.panel:
        # white-label: custom panel — still filtered to providers with keys
        custom = [
            {"provider": p["provider"], "model": p["model"], "label": p.get("label") or p["model"]}
            for p in cfg.panel
            if llm.provider_available(p.get("provider", ""))
        ]
        if len(custom) >= 2:
            return custom[:6]
    panel: list[dict[str, str]] = []
    if llm.provider_available("xai"):
        panel.append({"provider": "xai", "model": _xai_model(), "label": _xai_model()})
    if llm.provider_available("openai"):
        panel.append({"provider": "openai", "model": settings.ARENA_OPENAI_MODEL, "label": settings.ARENA_OPENAI_MODEL})
    if llm.provider_available("gemini"):
        panel.append({"provider": "gemini", "model": settings.ARENA_GEMINI_MODEL, "label": settings.ARENA_GEMINI_MODEL})
    if extra == "gemini-2.5-flash" and llm.provider_available("gemini"):
        panel.append({"provider": "gemini", "model": "gemini-2.5-flash", "label": "gemini-2.5-flash"})
    if extra == "grok-code-fast-1" and llm.provider_available("xai"):
        panel.append({"provider": "xai", "model": settings.ARENA_CODE_MODEL, "label": settings.ARENA_CODE_MODEL})
    # dedupe identical provider+model pairs (extra can collide with defaults)
    seen: set[tuple[str, str]] = set()
    out = []
    for p in panel:
        key = (p["provider"], p["model"])
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _skipped_warnings(extra: str | None) -> list[str]:
    notes = []
    if not llm.provider_available("openai"):
        notes.append("OpenAI skipped — set OPENAI_API_KEY to add it to the arena.")
    elif settings.ARENA_OPENAI_MODEL.startswith("gpt-5"):
        notes.append("OpenAI model defaulted to gpt-4o? (unreachable override ignored)")
    if not llm.provider_available("gemini"):
        notes.append("Gemini skipped — set GEMINI_API_KEY to add it to the arena.")
    if extra == "gemini-2.5-flash" and not llm.provider_available("gemini"):
        notes.append("gemini-2.5-flash needs GEMINI_API_KEY — extra ignored.")
    if extra == "grok-code-fast-1" and not llm.provider_available("xai"):
        notes.append("grok-code-fast-1 needs XAI_API_KEY — extra ignored.")
    return notes


def _parse_scores(text: str, letters: list[str]) -> dict[str, dict[str, int]]:
    """Extract the judge's optional {"scores": {"A": {"accuracy": n, "clarity": n}}} map."""
    try:
        m = re.search(r"\{.*\}", text, re.S)
        data = json.loads(m.group(0)) if m else {}
        raw = data.get("scores")
        out: dict[str, dict[str, int]] = {}
        if isinstance(raw, dict):
            for ltr, val in raw.items():
                ltr = str(ltr).strip().upper()[:1]
                if ltr in letters and isinstance(val, dict):
                    acc = max(1, min(10, int(val.get("accuracy", 0) or 0)))
                    cla = max(1, min(10, int(val.get("clarity", 0) or 0)))
                    if acc or cla:
                        out[ltr] = {"accuracy": acc, "clarity": cla}
        return out
    except Exception:
        return {}


def _parse_letter_json(text: str, key: str = "vote") -> tuple[str | None, str]:
    """Extract {"vote": "X", "rationale": "…"} style answers; tolerant of prose."""
    try:
        m = re.search(r"\{[^{}]*\}", text, re.S)
        data = json.loads(m.group(0)) if m else {}
        val = str(data.get(key, "")).strip().upper()[:1]
        why = str(data.get("rationale") or data.get("reason") or "").strip()[:220]
        if val in "ABCD":
            return val, why
    except Exception:
        pass
    m = re.search(rf"\b{key}\b[^A-D]*([A-D])\b", text, re.I)
    if m:
        return m.group(1).upper(), ""
    return None, ""


async def _stream_drafts(
    panel: list[dict[str, str]], question: str, prior_winner: str | None
) -> AsyncIterator[tuple[str, str, Any]]:
    """Fan out one token stream per contestant and multiplex them through a queue.

    Yields (label, "delta", text) as tokens arrive, (label, "usage", {"in","out"})
    when a provider reports token usage, and (label, "done", full_text) last.
    """
    system = DRAFT_SYSTEM + (REMATCH_NOTE.format(prior=prior_winner[:1200]) if prior_winner else "")
    queue: asyncio.Queue[tuple[str, str, Any]] = asyncio.Queue()

    async def worker(c: dict[str, str]) -> None:
        label = c["label"]
        buf: list[str] = []
        try:
            async for ev in llm.stream_chat(
                [{"role": "system", "content": system}, {"role": "user", "content": question}],
                model=c["model"],
                provider=c["provider"],
            ):
                if ev["type"] == "delta":
                    buf.append(ev["text"])
                    await queue.put((label, "delta", ev["text"]))
                elif ev["type"] == "usage":
                    u = ev.get("usage") or {}
                    await queue.put(
                        (
                            label,
                            "usage",
                            {"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0)},
                        )
                    )
        except Exception as e:
            if not buf:
                buf.append(f"(draft failed: {friendly_ai_error(e)})")
        finally:
            await queue.put((label, "done", "".join(buf).strip() or "(empty draft)"))

    tasks = [asyncio.create_task(worker(c)) for c in panel]
    pending = len(tasks)
    while pending:
        label, kind, payload = await queue.get()
        if kind == "done":
            pending -= 1
        yield (label, kind, payload)
    await asyncio.gather(*tasks, return_exceptions=True)


async def _draft(contestant: dict[str, str], question: str) -> dict[str, Any]:
    """Non-streaming fallback (solo-provider path)."""
    messages = [
        {"role": "system", "content": DRAFT_SYSTEM},
        {"role": "user", "content": question},
    ]
    usage: dict[str, int] = {}
    try:
        text = await llm.complete(
            messages,
            model=contestant["model"],
            temperature=0.5,
            max_tokens=1400,
            usage_out=usage,
            provider=contestant["provider"],
        )
    except Exception as e:
        text = f"(draft failed: {friendly_ai_error(e)})"
    return {
        "provider": contestant["provider"],
        "label": contestant["label"],
        "content": text.strip() or "(empty draft)",
        "usage": {
            "in": usage.get("prompt_tokens", 0),
            "out": usage.get("completion_tokens", 0),
        },
    }


async def _ballot(contestant: dict[str, str], question: str, letters: list[str], body: str) -> dict[str, Any]:
    usage: dict[str, int] = {}
    messages = [
        {"role": "system", "content": VOTE_SYSTEM},
        {"role": "user", "content": f"QUESTION:\n{question}\n\n{body}"},
    ]
    try:
        text = await llm.complete(
            messages, model=contestant["model"], temperature=0.1, max_tokens=220,
            usage_out=usage, provider=contestant["provider"],
        )
    except Exception:
        text = ""
    letter, why = _parse_letter_json(text, "vote")
    valid = bool(letter and letter in letters)
    return {
        "provider": contestant["label"],
        "letter": letter if valid else None,
        "rationale": why if valid else "",
        "valid": valid,
        "usage": {"in": usage.get("prompt_tokens", 0), "out": usage.get("completion_tokens", 0)},
    }


async def run_arena(
    question: str,
    extra: str | None = None,
    prior_winner: str | None = None,
    cfg: ArenaConfig | None = None,
) -> AsyncIterator[dict]:
    """Full arena flow yielding SSE-shaped event dicts (see module docstring)."""
    topic: dict = {"type": "topic", "topic": question[:180], "rematch": bool(prior_winner)}
    if cfg and cfg.brand:
        topic["brand"] = cfg.brand
    yield topic
    for note in _skipped_warnings(extra):
        yield {"type": "warning", "message": note}

    panel = _panel(extra, cfg)
    if len(panel) < 2:
        yield {"type": "warning", "message": "Arena needs 2+ providers — answered by the only configured one."}
        solo = panel[0] if panel else {"provider": "xai", "model": settings.MODEL_CHAT, "label": settings.MODEL_CHAT}
        d = await _draft(solo, question)
        yield {"type": "draft_start", "round": 1, "provider": solo["label"]}
        yield {"type": "draft_done", "round": 1, "provider": solo["label"], "content": d["content"]}
        yield {
            "type": "arena_verdict", "winner": solo["label"],
            "drafts": [{"provider": solo["label"], "content": d["content"][:2500], "round": 1}],
            "draft_order": ["A"], "votes": [], "scores": {}, "usage": {solo["label"]: d["usage"]},
        }
        for i in range(0, len(d["content"]), 160):
            yield {"type": "delta", "text": d["content"][i : i + 160]}
        yield {"type": "done"}
        return

    # 1) parallel drafts — streamed token-by-token as they generate
    for c in panel:
        yield {"type": "draft_start", "round": 1, "provider": c["label"]}
    done_by: dict[str, str] = {}
    usage_by: dict[str, dict[str, int]] = {}
    async for label, kind, payload in _stream_drafts(panel, question, prior_winner):
        if kind == "delta":
            yield {"type": "draft_delta", "provider": label, "text": payload}
        elif kind == "usage":
            usage_by[label] = payload
        else:  # done
            done_by[label] = payload
            yield {"type": "draft_done", "round": 1, "provider": label, "content": payload}
    drafts: list[dict[str, Any]] = [
        {
            "provider": c["provider"],
            "label": c["label"],
            "content": done_by.get(c["label"], "(draft missing)"),
            "usage": usage_by.get(c["label"], {"in": 0, "out": 0}),
        }
        for c in panel
    ]

    # 2) anonymize + blind ballots from every contestant
    order = list(range(len(drafts)))
    random.shuffle(order)
    letters = [chr(65 + i) for i in range(len(order))]  # A, B, C, (D)
    anon_blocks = "\n\n".join(
        f"ANSWER {letters[i]}:\n{drafts[order[i]]['content']}" for i in range(len(order))
    )
    ballots: list[dict[str, Any]] = await asyncio.gather(
        *[_ballot(c, question, letters, anon_blocks) for c in panel]
    )
    for b in ballots:
        yield (
            {"type": "vote_cast", "provider": b["provider"], "vote": b["letter"], "rationale": b["rationale"]}
            if b["valid"]
            else {"type": "vote_cast", "provider": b["provider"], "vote": None, "rationale": "", "invalid": True}
        )

    # 3) Grok-4 judge weighs drafts + ballots, scores every draft
    tally = "\n".join(
        f"- {b['provider']}: {b['letter']}" + (f" ({b['rationale']})" if b["rationale"] else "")
        for b in ballots
        if b["valid"]
    ) or "- (no valid ballots)"
    judge_usage: dict[str, int] = {}
    judge_model = (cfg.judge_model if cfg and cfg.judge_model else _xai_model()) or _xai_model()
    judge_label = (cfg.brand + " judge") if cfg and cfg.brand else judge_model
    winner_letter: str | None = None
    scores: dict[str, dict[str, int]] = {}
    try:
        judge_text = await llm.complete(
            [
                {"role": "system", "content": _judge_system(cfg)},
                {"role": "user", "content": f"QUESTION:\n{question}\n\n{anon_blocks}\n\nBALLOTS:\n{tally}"},
            ],
            model=judge_model,
            temperature=0.1,
            max_tokens=420,
            usage_out=judge_usage,
            provider="xai",
        )
        winner_letter, _ = _parse_letter_json(judge_text, "winner")
        scores = _parse_scores(judge_text, letters)
    except Exception as e:
        log.warning("arena judge failed: %s", e)
    if not winner_letter or winner_letter not in letters:
        # judge fallback: most votes, else first anonymous slot
        counts = {ltr: 0 for ltr in letters}
        for b in ballots:
            if b["valid"] and b["letter"]:
                counts[b["letter"]] += 1
        winner_letter = max(counts, key=lambda k: counts[k]) if any(counts.values()) else letters[0]

    winner_idx = letters.index(winner_letter)
    winner = drafts[order[winner_idx]]
    usage: dict[str, dict[str, int]] = {}
    for d in drafts:
        usage[d["label"]] = d["usage"]
    for b in ballots:
        u = usage.setdefault(b["provider"], {"in": 0, "out": 0})
        u["in"] += b["usage"]["in"]
        u["out"] += b["usage"]["out"]
    j = usage.setdefault(judge_model, {"in": 0, "out": 0})
    j["in"] += judge_usage.get("prompt_tokens", 0)
    j["out"] += judge_usage.get("completion_tokens", 0)

    drafts_meta = []
    for i, ltr in enumerate(letters):
        d = drafts[order[i]]
        drafts_meta.append({"provider": d["label"], "content": d["content"][:2500], "round": 1, "slot": ltr})
    yield {
        "type": "arena_verdict",
        "winner": winner["label"],
        "judge": judge_label,
        "brand": cfg.brand if cfg and cfg.brand else None,
        "drafts": drafts_meta,           # index i ↔ draft_order[i]
        "draft_order": letters,
        "scores": scores,                # slot letter → {accuracy, clarity} 1–10
        "votes": [
            {
                "provider": b["provider"],
                "ballot": {"vote": b["letter"], "rationale": b["rationale"]} if b["valid"] else None,
                "valid": b["valid"],
            }
            for b in ballots
        ],
        "usage": usage,
    }

    # 4) stream the winning draft as the final answer
    content = winner["content"]
    for i in range(0, len(content), 160):
        yield {"type": "delta", "text": content[i : i + 160]}
    yield {"type": "done"}
