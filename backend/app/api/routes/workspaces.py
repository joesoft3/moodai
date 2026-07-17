"""Team workspaces: members share conversations; owners manage members and see per-seat usage.
Invite links let anyone with the link join — optionally gated to a bound domain's email addresses."""

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.models import (
    Conversation,
    Domain,
    PluginConnection,
    UsageEvent,
    User,
    Workspace,
    WorkspaceInvite,
    WorkspaceMember,
)
from ...db.session import get_db
from ...schemas import InviteEmailRequest, MemberAdd, WorkspaceCreate, WorkspaceJoinRequest
from ...services.notify import send_email
from ..deps import enforce_rate_limit, get_current_user

router = APIRouter()


async def membership_of(db: AsyncSession, workspace_id: str, user_id: str) -> WorkspaceMember | None:
    return await db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id
        )
    )


async def require_member(db: AsyncSession, wid: str, uid: str) -> WorkspaceMember:
    m = await membership_of(db, wid, uid)
    if not m:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this workspace")
    return m


async def require_owner(db: AsyncSession, wid: str, uid: str) -> WorkspaceMember:
    m = await require_member(db, wid, uid)
    if m.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Owners only")
    return m


def _invite_out(i: WorkspaceInvite) -> dict:
    return {
        "id": i.id,
        "token": i.token,
        "expires_at": i.expires_at.isoformat() if i.expires_at else None,
        "revoked": i.revoked,
        "created_at": i.created_at.isoformat() if i.created_at else None,
    }


# --------------------------------------------------------------------- invite links + join
@router.post("/{wid}/invites", status_code=201)
async def create_invite(wid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await require_owner(db, wid, user.id)
    inv = WorkspaceInvite(
        workspace_id=wid,
        created_by=user.id,
        token=secrets.token_urlsafe(16),
        expires_at=datetime.now(timezone.utc) + timedelta(days=max(1, settings.INVITE_TTL_DAYS)),
    )
    db.add(inv)
    await db.commit()
    return _invite_out(inv)


@router.get("/{wid}/invites")
async def list_invites(wid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await require_owner(db, wid, user.id)
    rows = (
        await db.execute(
            select(WorkspaceInvite)
            .where(WorkspaceInvite.workspace_id == wid)
            .order_by(WorkspaceInvite.created_at.desc())
            .limit(20)
        )
    ).scalars().all()
    return {"invites": [_invite_out(i) for i in rows]}


@router.post("/{wid}/invites/email")
async def email_invites(
    wid: str, req: InviteEmailRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Email the workspace's invite link to teammates — sent through the OWNER's
    connected Gmail plugin (fallback: the link is returned for copy-paste)."""
    await require_owner(db, wid, user.id)
    await enforce_rate_limit(f"invemail:{user.id}", 10)
    gmail = await db.scalar(
        select(PluginConnection).where(
            PluginConnection.user_id == user.id, PluginConnection.provider == "gmail"
        )
    )
    if not gmail:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Connect Gmail (Settings → Connected apps) to send invites by email — or copy the link instead.",
        )
    ws = await db.get(Workspace, wid)
    if not ws:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")

    # reuse an existing valid link if there is one, else mint a fresh one
    now = datetime.now(timezone.utc)
    inv = await db.scalar(
        select(WorkspaceInvite)
        .where(WorkspaceInvite.workspace_id == wid, WorkspaceInvite.revoked.is_(False))
        .order_by(WorkspaceInvite.created_at.desc())
        .limit(1)
    )
    inv_exp = None
    if inv and inv.expires_at:
        inv_exp = inv.expires_at if inv.expires_at.tzinfo else inv.expires_at.replace(tzinfo=timezone.utc)
    if not inv or (inv_exp and inv_exp < now):
        inv = WorkspaceInvite(
            workspace_id=wid,
            created_by=user.id,
            token=secrets.token_urlsafe(16),
            expires_at=now + timedelta(days=max(1, settings.INVITE_TTL_DAYS)),
        )
        db.add(inv)
        await db.commit()

    link = f"{settings.FRONTEND_URL}/join/{inv.token}"
    gates = (
        await db.execute(select(Domain).where(Domain.workspace_id == wid, Domain.status == "active"))
    ).scalars().all()
    gate_line = (
        f"\nNote: only accounts on @{gates[0].domain} email addresses can accept this invite."
        if gates else ""
    )
    subject = f"👥 {user.display_name or user.email} invited you to {ws.name} on Mood AI"
    body = (
        f"Hi,\n\nYou've been invited to join the “{ws.name}” team workspace on Mood AI — "
        f"shared conversations, files and agents with your team.\n\n"
        f"Join here (link expires {inv_exp.date().isoformat() if inv_exp else 'soon'}): {link}\n"
        f"{gate_line}\n\n"
        f"— Sent via Mood AI"
    )
    sent, failed = 0, []
    for e in dict.fromkeys(x.lower() for x in req.emails):  # dedupe, keep order
        if await send_email(db, user.id, e, subject, body):
            sent += 1
        else:
            failed.append(e)
    return {"sent": sent, "failed": failed, "invite": _invite_out(inv), "link": link}


@router.delete("/{wid}/invites/{iid}")
async def revoke_invite(
    wid: str, iid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    await require_owner(db, wid, user.id)
    inv = await db.get(WorkspaceInvite, iid)
    if not inv or inv.workspace_id != wid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found")
    inv.revoked = True
    await db.commit()
    return {"revoked": iid}


@router.post("/join")
async def join_workspace(
    req: WorkspaceJoinRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Redeem an invite link. If the workspace has an ACTIVE bound domain, only
    accounts whose email lives on that domain (or its parent/subdomain) may join —
    e.g. bound chat.acme.com admits jane@acme.com and jane@chat.acme.com."""
    inv = await db.scalar(select(WorkspaceInvite).where(WorkspaceInvite.token == req.token))
    if not inv or inv.revoked:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite link is invalid or revoked")
    exp = inv.expires_at
    if exp and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp and exp < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_410_GONE, "Invite link has expired — ask the owner for a fresh one")
    ws = await db.get(Workspace, inv.workspace_id)
    if not ws:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace no longer exists")
    if await membership_of(db, ws.id, user.id):
        return {"joined": True, "already_member": True, "workspace": {"id": ws.id, "name": ws.name}}

    gates = (
        await db.execute(select(Domain).where(Domain.workspace_id == ws.id, Domain.status == "active"))
    ).scalars().all()
    if gates:
        email_dom = user.email.split("@")[-1].lower()
        ok = any(
            email_dom == g.domain or email_dom.endswith("." + g.domain) or g.domain.endswith("." + email_dom)
            for g in gates
        )
        if not ok:
            allowed = ", ".join("@" + g.domain for g in gates)
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"This workspace only accepts accounts on its company domain ({allowed}) — sign up with your work email.",
            )
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="member"))
    await db.commit()
    return {"joined": True, "already_member": False, "workspace": {"id": ws.id, "name": ws.name}}


async def _member_out(db: AsyncSession, m: WorkspaceMember) -> dict:
    u = await db.get(User, m.user_id)
    return {
        "user_id": m.user_id,
        "email": u.email if u else None,
        "display_name": (u.display_name if u else None),
        "role": m.role,
    }


@router.get("")
async def list_workspaces(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        await db.execute(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id))
    ).scalars().all()
    out = []
    for m in rows:
        ws = await db.get(Workspace, m.workspace_id)
        if not ws:
            continue
        count = int(
            (await db.scalar(
                select(func.count(WorkspaceMember.id)).where(WorkspaceMember.workspace_id == ws.id)
            ))
            or 0
        )
        out.append({"id": ws.id, "name": ws.name, "role": m.role, "owner": ws.owner_id == user.id, "member_count": count})
    return {"workspaces": out}


@router.post("", status_code=201)
async def create_workspace(
    req: WorkspaceCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    ws = Workspace(name=req.name.strip()[:120], owner_id=user.id)
    db.add(ws)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))
    await db.commit()
    return {"id": ws.id, "name": ws.name, "role": "owner"}


@router.get("/{wid}")
async def workspace_detail(wid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await require_member(db, wid, user.id)
    ws = await db.get(Workspace, wid)
    if not ws:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    rows = (
        await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == wid))
    ).scalars().all()
    return {
        "id": ws.id,
        "name": ws.name,
        "owner_id": ws.owner_id,
        "members": [await _member_out(db, m) for m in rows],
    }


@router.post("/{wid}/members", status_code=201)
async def add_member(
    wid: str, req: MemberAdd, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    me = await require_member(db, wid, user.id)
    if me.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners can add members")
    target = await db.scalar(select(User).where(User.email == req.email.lower()))
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No Mood account with that email — ask them to sign up first")
    if await membership_of(db, wid, target.id):
        return {"added": True, "already_member": True}
    db.add(WorkspaceMember(workspace_id=wid, user_id=target.id, role=req.role))
    await db.commit()
    return {"added": True, "already_member": False}


@router.delete("/{wid}/members/{uid}")
async def remove_member(
    wid: str, uid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    me = await require_member(db, wid, user.id)
    if me.role != "owner" and uid != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners can remove members")
    ws = await db.get(Workspace, wid)
    if ws and ws.owner_id == uid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The workspace owner can't be removed")
    await db.execute(
        delete(WorkspaceMember).where(WorkspaceMember.workspace_id == wid, WorkspaceMember.user_id == uid)
    )
    await db.commit()
    return {"removed": uid}


@router.get("/{wid}/conversations")
async def workspace_conversations(wid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Shared conversations of the workspace (every member can read them)."""
    await require_member(db, wid, user.id)
    rows = (
        await db.execute(
            select(Conversation)
            .where(Conversation.workspace_id == wid)
            .order_by(Conversation.updated_at.desc())
        )
    ).scalars().all()
    author_ids = {c.user_id for c in rows}
    authors: dict[str, str] = {}
    for uid in author_ids:
        u = await db.get(User, uid)
        if u:
            authors[uid] = u.display_name or u.email.split("@")[0]
    return {
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "author": authors.get(c.user_id, "?"),
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in rows
        ],
        "authors": authors,
    }


@router.get("/{wid}/usage")
async def workspace_usage(wid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Per-seat usage this calendar month (owners only)."""
    me = await require_member(db, wid, user.id)
    if me.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Owners only")
    now_rows = await db.execute(
        select(func.date_trunc("month", func.now()))
    )
    month_start = now_rows.scalar()
    member_ids = (
        await db.execute(select(WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == wid))
    ).scalars().all()
    rows = (
        await db.execute(
            select(
                UsageEvent.user_id,
                func.count(UsageEvent.id),
                func.coalesce(func.sum(UsageEvent.tokens_in + UsageEvent.tokens_out), 0),
            )
            .where(UsageEvent.user_id.in_(member_ids), UsageEvent.created_at >= month_start)
            .group_by(UsageEvent.user_id)
        )
    ).all()
    by_user = {uid_: {"requests": int(c), "tokens": int(t)} for uid_, c, t in rows}
    seats = []
    for uid_ in member_ids:
        u = await db.get(User, uid_)
        seats.append(
            {
                "user_id": uid_,
                "email": u.email if u else None,
                "plan": u.plan if u else "free",
                "requests_month": by_user.get(uid_, {}).get("requests", 0),
                "tokens_month": by_user.get(uid_, {}).get("tokens", 0),
            }
        )
    return {"seats": seats}
