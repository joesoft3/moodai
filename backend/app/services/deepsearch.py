"""DeepSearch — agentic multi-round research (Grok-style DeepSearch/DeeperSearch).

Pipeline:
  1. Decompose the goal into focused research questions (planner)
  2. Round loop: run the question queue with xAI Live Search (concurrently)
  3. Gap analysis between rounds → follow-up questions (this is the "deep" part)
  4. Synthesize a comprehensive markdown report with inline [n](url) citations
"""

import json
import logging

from ..config import settings
from .llm import llm

log = logging.getLogger(__name__)

DECOMPOSE_PROMPT = """You are the Research Planner of a deep-research system.
Break the user's goal into {n} focused, non-overlapping research questions that,
answered together, fully cover the goal. Prefer specific, searchable questions.
Return STRICT JSON only: {{"questions": ["...", "..."]}}"""

RESEARCH_PROMPT = (
    "You are a research engine with live web access. Answer the query with precise, "
    "factual, information-dense bullets. Every claim must trace to a source URL. "
    "No fluff, no disclaimers."
)

GAP_PROMPT = """You are the Gap Analyst of a deep-research system.
GOAL: {goal}

FINDINGS SO FAR (truncated):
{findings}

What is still missing to write a comprehensive report? Return STRICT JSON only:
{{"assessment": "one sentence", "followups": ["specific search query"]}}
Rules: max {n} followups; return [] when coverage is already sufficient."""

SYNTH_PROMPT = """You are DeepMood, an expert research writer.
Using ONLY the findings and the numbered source list below, write a comprehensive,
well-structured markdown report that fully answers the user's goal.
- Cite claims INLINE as [n](url) using the source-list numbering.
- Use ## headings, bullets, and tables where they help. Be thorough but organized.
- End with a short "**Bottom line**" paragraph.

GOAL: {goal}

FINDINGS:
{findings}

SOURCES:
{sources}
"""


def _strip_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def depth_config(depth: str) -> tuple[int, int]:
    """(rounds, initial_questions). deep = 2×4, deeper = 3×5, anything else = deep."""
    return (3, 5) if depth == "deeper" else (2, 4)


async def decompose(goal: str, n: int) -> list[str]:
    try:
        raw = await llm.complete(
            [
                {"role": "system", "content": DECOMPOSE_PROMPT.format(n=n)},
                {"role": "user", "content": goal},
            ],
            model=settings.MODEL_CHAT,
            temperature=0.2,
            max_tokens=400,
        )
        qs = json.loads(_strip_fence(raw)).get("questions") or []
        qs = [q.strip() for q in qs if isinstance(q, str) and q.strip()][:n]
        if qs:
            return qs
    except Exception as e:
        log.warning("decompose failed, using goal as single question: %s", e)
    return [goal]


async def research_query(query: str) -> tuple[str, list[str]]:
    """One live-search research pass → (findings_text, citation_urls)."""
    return await llm.complete_with_search(
        [
            {"role": "system", "content": RESEARCH_PROMPT},
            {"role": "user", "content": query},
        ],
        model=settings.MODEL_CHAT,
        temperature=0.4,
    )


async def gap_analysis(
    goal: str, findings: list[tuple[str, str]], n: int
) -> tuple[str, list[str]]:
    """Returns (assessment_sentence, followup_queries)."""
    digest = "\n\n".join(f"[{q}]\n{txt[:1200]}" for q, txt in findings)
    digest = digest[:6000]
    try:
        raw = await llm.complete(
            [
                {"role": "system", "content": GAP_PROMPT.format(goal=goal, findings=digest, n=n)},
                {"role": "user", "content": "Analyze coverage now."},
            ],
            model=settings.MODEL_CHAT,
            temperature=0.2,
            max_tokens=400,
        )
        data = json.loads(_strip_fence(raw))
        followups = [q.strip() for q in (data.get("followups") or []) if isinstance(q, str) and q.strip()][:n]
        return (data.get("assessment") or "").strip(), followups
    except Exception as e:
        log.warning("gap analysis failed: %s", e)
        return "", []


def build_synthesis_messages(goal: str, findings: list[tuple[str, str]], sources: list[str]) -> list[dict]:
    finding_blocks = "\n\n".join(f"### Research on: {q}\n{txt[:2000]}" for q, txt in findings)
    source_lines = "\n".join(f"[{i+1}] {u}" for i, u in enumerate(sources))
    return [
        {
            "role": "system",
            "content": SYNTH_PROMPT.format(goal=goal, findings=finding_blocks[:12000], sources=source_lines),
        },
        {"role": "user", "content": "Write the report now."},
    ]
