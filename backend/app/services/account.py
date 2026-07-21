"""🗑 Account deletion — permanent self-service erasure.

Google Play and the App Store both require in-app account deletion. One call
here removes every trace of a user:

- **Database** — explicit, children-first deletes (works on any engine even
  if FK cascades aren't enforced, e.g. sqlite without the pragma). Personal
  conversations, authored messages anywhere (incl. team chats), uploads,
  designs, films, edits, orders, brand kit, plugin tokens, devices, usage,
  subscription, domains, shared links, staged approvals. **Owned teams are
  dissolved** (memberships/invites/team conversations); memberships in other
  people's teams are simply left.
- **Disk** — uploaded file blobs, design PNG tiers, film video/poster, edit
  sources/outputs (all unlinked defensively; janitor would get media anyway).
- **Vectors** — the user's Qdrant memory points (best-effort, never fatal).

Frontend flows keep a copy of the summary for undo-free confirmation UX.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from . import storage
from ..db import models as M


async def collect_user_media(db: AsyncSession, user_id: str) -> list:
    """Every stored path owned by the user — absolute upload blobs, MEDIA_DIR
    basenames resolved to paths, and 'r2:<key>' remote markers (kept as str)."""
    paths: list = []
    uploads = (await db.execute(select(M.FileAsset.path).where(M.FileAsset.user_id == user_id))).scalars().all()
    for p_ in uploads:
        if p_:
            paths.append(p_ if p_.startswith("r2:") else Path(p_))
    media = Path(settings.MEDIA_DIR)

    def basenames(names: list[str | None]) -> None:
        for n in names:
            if n and Path(n).name == n:  # basename-only guard against traversal
                paths.append(media / n)

    for file, prt in (await db.execute(
        select(M.Design.file, M.Design.print_file).where(M.Design.user_id == user_id)
    )):
        basenames([file, prt])
    for fn, poster in (await db.execute(
        select(M.Film.filename, M.Film.poster).where(M.Film.user_id == user_id)
    )):
        basenames([fn, poster])
    for src, out in (await db.execute(
        select(M.Edit.src_name, M.Edit.out_name).where(M.Edit.user_id == user_id)
    )):
        basenames([src, out])
    return paths


async def unlink_media(paths: list) -> int:
    """Delete across both storage backends (local paths + r2: markers)."""
    removed = 0
    for p in paths:
        if await storage.delete(str(p)):
            removed += 1
    return removed


async def purge_memories(user_id: str) -> None:
    """Erase vector memories — best-effort: memory outage must never block deletion."""
    try:
        from .memory import clear_memories

        await clear_memories(user_id)
    except Exception:
        pass


async def delete_user_data(db: AsyncSession, user: M.User) -> dict[str, Any]:
    """Erase everything, then commit. Returns a small summary for UX/audit counters."""
    uid = user.id
    media_paths = await collect_user_media(db, uid)
    my_convs = (await db.execute(
        select(M.Conversation.id).where(M.Conversation.user_id == uid)
    )).scalars().all()
    owned_ws = (await db.execute(
        select(M.Workspace.id).where(M.Workspace.owner_id == uid)
    )).scalars().all()

    # children of *my* conversations (links, staged approvals, others' replies)
    if my_convs:
        await db.execute(delete(M.Message).where(M.Message.conversation_id.in_(my_convs)))
        await db.execute(delete(M.SharedLink).where(M.SharedLink.conversation_id.in_(my_convs)))
        await db.execute(delete(M.PendingAction).where(M.PendingAction.conversation_id.in_(my_convs)))

    # everything authored anywhere (incl. messages inside other teams' chats)
    await db.execute(delete(M.Message).where(M.Message.user_id == uid))
    await db.execute(delete(M.SharedLink).where(M.SharedLink.user_id == uid))
    await db.execute(delete(M.PendingAction).where(M.PendingAction.user_id == uid))
    await db.execute(delete(M.FileAsset).where(M.FileAsset.user_id == uid))
    await db.execute(delete(M.Conversation).where(M.Conversation.user_id == uid))
    await db.execute(delete(M.Film).where(M.Film.user_id == uid))
    await db.execute(delete(M.Design).where(M.Design.user_id == uid))
    await db.execute(delete(M.Edit).where(M.Edit.user_id == uid))
    await db.execute(delete(M.DesignOrder).where(M.DesignOrder.owner_id == uid))
    await db.execute(delete(M.BrandKit).where(M.BrandKit.user_id == uid))
    await db.execute(delete(M.PluginConnection).where(M.PluginConnection.user_id == uid))
    await db.execute(delete(M.Device).where(M.Device.user_id == uid))
    await db.execute(delete(M.UsageEvent).where(M.UsageEvent.user_id == uid))
    await db.execute(delete(M.Subscription).where(M.Subscription.user_id == uid))
    await db.execute(delete(M.Domain).where(M.Domain.user_id == uid))

    # teams: dissolve owned workspaces entirely, simply leave the others
    for ws in owned_ws:
        ws_convs = (await db.execute(
            select(M.Conversation.id).where(M.Conversation.workspace_id == ws)
        )).scalars().all()
        if ws_convs:
            await db.execute(delete(M.Message).where(M.Message.conversation_id.in_(ws_convs)))
            await db.execute(delete(M.SharedLink).where(M.SharedLink.conversation_id.in_(ws_convs)))
            await db.execute(delete(M.PendingAction).where(M.PendingAction.conversation_id.in_(ws_convs)))
        await db.execute(delete(M.Conversation).where(M.Conversation.workspace_id == ws))
        await db.execute(delete(M.WorkspaceInvite).where(M.WorkspaceInvite.workspace_id == ws))
        await db.execute(delete(M.WorkspaceMember).where(M.WorkspaceMember.workspace_id == ws))
    await db.execute(delete(M.WorkspaceInvite).where(M.WorkspaceInvite.created_by == uid))
    await db.execute(delete(M.WorkspaceMember).where(M.WorkspaceMember.user_id == uid))
    if owned_ws:
        await db.execute(delete(M.Workspace).where(M.Workspace.id.in_(owned_ws)))

    await db.delete(user)
    await db.commit()

    await purge_memories(uid)
    files_removed = await unlink_media(media_paths)
    return {
        "conversations_removed": len(my_convs),
        "teams_dissolved": len(owned_ws),
        "files_removed": files_removed,
    }
