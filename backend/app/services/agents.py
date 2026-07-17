"""Multi-agent mode v1 (ARCHITECTURE.md §11).

Pipeline: Planner decomposes the goal → role agents (researcher with Live Search,
coder, writer) execute on the shared context → writer synthesizes the final answer.
All agents run on the same LLMService with per-role system prompts.
"""

import json
import logging

from ..config import settings
from .llm import llm

log = logging.getLogger(__name__)

PLANNER_PROMPT = """You are the Planner of a multi-agent AI team.
Decompose the user's goal into 2-4 steps executed by specialist agents:
- "researcher": finds current, factual information on the web (has live search)
- "coder": writes and reasons about code
- "writer": synthesizes material into polished prose (MUST be the final step)
Return STRICT JSON only, no prose:
{"steps":[{"agent":"researcher|coder|writer","task":"..."}]}"""

CRITIC_PROMPT = (
    "You are the Critic on a multi-agent AI team — the final quality gate.\n"
    "Given the user's goal, the team's findings, and the draft answer:\n"
    "1. Check the draft against the goal: missing sub-questions, factual errors, "
    "contradictions, weak structure, uncited claims.\n"
    "2. Fix every issue directly. Preserve any source URLs as [n](url) citations.\n"
    "Return ONLY the improved final answer in polished markdown (same language as the "
    "goal). No meta-commentary about what you changed."
)


ROLE_PROMPTS = {
    "researcher": (
        "You are Researcher on a multi-agent AI team. Use web search to find accurate, "
        "current facts for your task. Return concise bullet facts WITH source URLs."
    ),
    "coder": (
        "You are Coder on a multi-agent AI team. Produce correct, runnable code for your "
        "task, followed by a brief explanation. Be precise; no fluff."
    ),
    "writer": (
        "You are Writer on a multi-agent AI team. Synthesize the goal and your team's "
        "findings into a polished, well-structured markdown answer. Cite sources as [n](url) "
        "when the material includes them."
    ),
}


def _strip_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


async def plan(goal: str) -> list[dict]:
    """Decompose the goal into role-agent steps (fallback plan on any failure)."""
    try:
        raw = await llm.complete(
            [
                {"role": "system", "content": PLANNER_PROMPT},
                {"role": "user", "content": goal},
            ],
            model=settings.MODEL_CHAT,
            temperature=0.2,
            max_tokens=400,
        )
        steps = json.loads(_strip_fence(raw)).get("steps") or []
        steps = [s for s in steps if isinstance(s, dict) and s.get("agent") in ROLE_PROMPTS and s.get("task")][:4]
        if steps:
            return steps
    except Exception as e:
        log.warning("planner failed, using fallback plan: %s", e)
    return [
        {"agent": "researcher", "task": goal},
        {"agent": "writer", "task": "Synthesize the research into a complete answer to the goal."},
    ]


async def run_agent(
    agent: str,
    task: str,
    goal: str,
    prior: list[tuple[str, str, str]],
    usage_out: dict | None = None,
) -> tuple[str, list[str]]:
    """Execute one role agent. Returns (output_text, citations)."""
    context_parts = [f"OVERALL GOAL: {goal}"]
    for a, t, out in prior:
        context_parts.append(f"[{a} — {t}]\n{out[:2500]}")
    user_msg = "\n\n".join(context_parts) + f"\n\nYOUR TASK ({agent}): {task}"
    messages = [
        {"role": "system", "content": ROLE_PROMPTS[agent]},
        {"role": "user", "content": user_msg},
    ]
    # Multi-provider router: coder → PROVIDER_CODING, writer → PROVIDER_AGENTS;
    # researcher stays on xAI (Live Search is xAI-only).
    task_key = "coding" if agent == "coder" else "agents"
    provider, model = llm.route(task_key)
    if agent == "researcher":
        return await llm.complete_with_search(
            messages, model=settings.MODEL_CHAT, temperature=0.4, usage_out=usage_out
        )
    text = await llm.complete(
        messages, model=model, temperature=0.4 if agent == "writer" else 0.3,
        usage_out=usage_out, provider=provider,
    )
    return text, []


async def critic_review(
    goal: str, draft: str, prior: list[tuple[str, str, str]], usage_out: dict | None = None
) -> str:
    """Final gate: the critic fact-checks, fills gaps and polishes the writer's draft."""
    findings = "\n\n".join(f"[{a} — {t}]\n{o[:2000]}" for a, t, o in prior)
    provider, model = llm.route("agents")
    return await llm.complete(
        [
            {"role": "system", "content": CRITIC_PROMPT},
            {
                "role": "user",
                "content": f"GOAL: {goal}\n\nTEAM FINDINGS:\n{findings}\n\nDRAFT ANSWER:\n{draft}",
            },
        ],
        model=model,
        temperature=0.3,
        usage_out=usage_out,
        provider=provider,
    )
