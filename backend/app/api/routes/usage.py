import csv
import io
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import UsageEvent, User
from ...db.session import get_db
from ...services.metering import usage_summary
from ..deps import get_current_user

router = APIRouter()


@router.get("/summary")
async def get_usage_summary(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Current-month usage meters vs. plan limits + 14-day token series."""
    return await usage_summary(db, user.id, user.plan)


@router.get("/export")
async def export_usage_csv(
    days: int = Query(default=30, ge=1, le=95),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Download your raw usage events as CSV (default: last 30 days, max 10k rows)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(UsageEvent)
            .where(UsageEvent.user_id == user.id, UsageEvent.created_at >= since)
            .order_by(UsageEvent.created_at)
            .limit(10_000)
        )
    ).scalars().all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["created_at", "kind", "model", "tokens_in", "tokens_out", "estimated"])
    for r in rows:
        w.writerow([
            r.created_at.isoformat() if r.created_at else "",
            r.kind,
            r.model or "",
            r.tokens_in,
            r.tokens_out,
            int(bool(r.estimated)),
        ])
    fname = f"mood-usage-{since.date().isoformat()}..{datetime.now(timezone.utc).date().isoformat()}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
