"""Usage metering: one UsageEvent per user-facing AI action, powering the
Settings usage dashboard and plan-tier limits. Token counts come from the
provider when available (`stream_options=include_usage` / response.usage);
otherwise a chars/4 heuristic is recorded with estimated=True."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from ..db.models import UsageEvent
from ..db.session import SessionLocal

log = logging.getLogger(__name__)

# Plan tiers (per-calendar-month unless the key says _day). 0 = unlimited.
PLAN_LIMITS: dict[str, dict[str, int]] = {
    "free": {"tokens_month": 200_000, "images_month": 20, "deepsearch_day": 10, "agent_day": 15, "video_day": 3, "design_day": 5, "edit_day": 3, "arena_day": 3, "upload_mb": 25, "mem_days": 30},
    "pro": {"tokens_month": 5_000_000, "images_month": 500, "deepsearch_day": 200, "agent_day": 300, "video_day": 60, "design_day": 60, "edit_day": 30, "arena_day": 100, "upload_mb": 50, "mem_days": 365},
}


def plan_rate_mult(plan: str) -> int:
    """🧰 Pro perk — 4× per-minute rate-limit throughput for paid plans."""
    return {"pro": 4}.get(plan, 1)


async def count_today(db, user_id: str, kind: str) -> int:
    """How many `kind` usage events the user has triggered today (UTC) — for plan caps."""
    today, _ = period_starts()
    return int(
        (
            await db.scalar(
                select(func.count(UsageEvent.id)).where(
                    UsageEvent.user_id == user_id, UsageEvent.kind == kind, UsageEvent.created_at >= today
                )
            )
        )
        or 0
    )


def add_tokens(dst: dict, usage: dict | None) -> None:
    """Accumulate provider usage into a totals dict."""
    dst["tokens_in"] = dst.get("tokens_in", 0) + int((usage or {}).get("prompt_tokens", 0))
    dst["tokens_out"] = dst.get("tokens_out", 0) + int((usage or {}).get("completion_tokens", 0))
    if usage:
        dst["estimated"] = False


def estimate_tokens(text_in: str, text_out: str) -> dict:
    return {
        "tokens_in": max(1, len(text_in) // 4),
        "tokens_out": max(1, len(text_out) // 4),
        "estimated": True,
    }


async def record_usage(
    user_id: str,
    kind: str,
    model: str | None = None,
    *,
    tokens_in: int = 0,
    tokens_out: int = 0,
    estimated: bool = False,
) -> None:
    """Best-effort: never let metering break a user request."""
    try:
        async with SessionLocal() as s:
            s.add(
                UsageEvent(
                    user_id=user_id,
                    kind=kind,
                    model=model,
                    tokens_in=max(0, int(tokens_in)),
                    tokens_out=max(0, int(tokens_out)),
                    estimated=bool(estimated),
                )
            )
            await s.commit()
    except Exception as e:
        log.warning("usage metering failed: %s", e)


def period_starts() -> tuple[datetime, datetime]:
    """(start of today UTC, start of this calendar month UTC)."""
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = today.replace(day=1)
    return today, month


async def usage_summary(db, user_id: str, plan: str) -> dict:
    """Aggregates used by the Settings dashboard (current month + today + 14-day series)."""
    today, month = period_starts()
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])

    # Month: tokens + counts per kind
    rows = (
        await db.execute(
            select(
                UsageEvent.kind,
                func.count(UsageEvent.id),
                func.coalesce(func.sum(UsageEvent.tokens_in), 0),
                func.coalesce(func.sum(UsageEvent.tokens_out), 0),
            )
            .where(UsageEvent.user_id == user_id, UsageEvent.created_at >= month)
            .group_by(UsageEvent.kind)
        )
    ).all()
    by_kind = {k: {"count": int(c), "tokens_in": int(ti), "tokens_out": int(to)} for k, c, ti, to in rows}
    tokens_month = sum(v["tokens_in"] + v["tokens_out"] for v in by_kind.values())

    # Today: counts per kind
    rows = (
        await db.execute(
            select(UsageEvent.kind, func.count(UsageEvent.id))
            .where(UsageEvent.user_id == user_id, UsageEvent.created_at >= today)
            .group_by(UsageEvent.kind)
        )
    ).all()
    today_by_kind = {k: int(c) for k, c in rows}

    # 14-day token series (for the mini chart)
    rows = (
        await db.execute(
            select(
                func.date(UsageEvent.created_at),
                func.coalesce(func.sum(UsageEvent.tokens_in + UsageEvent.tokens_out), 0),
            )
            .where(
                UsageEvent.user_id == user_id,
                UsageEvent.created_at >= today - timedelta(days=13),
            )
            .group_by(func.date(UsageEvent.created_at))
        )
    ).all()
    per_day = {str(d): int(t) for d, t in rows}
    series = [
        {"date": str((today - timedelta(days=i)).date()), "tokens": per_day.get(str((today - timedelta(days=i)).date()), 0)}
        for i in range(13, -1, -1)
    ]

    def meter(used: int, limit: int) -> dict:
        return {"used": used, "limit": limit, "unlimited": limit == 0, "pct": 0 if limit == 0 else min(100, round(used / limit * 100))}

    return {
        "plan": plan,
        "tokens_month": meter(tokens_month, limits["tokens_month"]),
        "images_month": meter(by_kind.get("image", {}).get("count", 0), limits["images_month"]),
        "deepsearch_day": meter(today_by_kind.get("deepsearch", 0), limits["deepsearch_day"]),
        "agent_day": meter(today_by_kind.get("agent", 0), limits["agent_day"]),
        "video_day": meter(today_by_kind.get("video", 0), limits.get("video_day", 0)),
        "arena_day": meter(today_by_kind.get("arena", 0), limits.get("arena_day", 0)),
        "by_kind_month": by_kind,
        "today_by_kind": today_by_kind,
        "daily_tokens": series,
    }
