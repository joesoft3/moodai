"""v1.3.0 units — 🗑 account deletion (Play/App Store compliance).

Full-DB erase against an in-memory sqlite engine: every owned table emptied,
media files unlinked, owned teams dissolved, memberships in other teams cut,
and other users' data untouched."""

import asyncio
import uuid

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import models as M
from app.db.base import Base
from app.services import account as acct


def _uid() -> str:
    return uuid.uuid4().hex


@pytest.fixture()
def session(tmp_path, monkeypatch):
    """Isolated in-memory DB session factory + tmp MEDIA_DIR."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    async def _make():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_make())
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.config.settings.MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(acct, "purge_memories", lambda uid: asyncio.sleep(0))
    media = tmp_path
    yield factory, media
    asyncio.run(engine.dispose())


def _mk_user(email: str) -> M.User:
    return M.User(id=_uid(), email=email, hashed_password="x", display_name=email)


def _seed_everything(user: M.User, media) -> dict:
    """One of everything the user can own; returns ids/paths to assert on."""
    m = dict(u=_uid())
    conv = M.Conversation(id=_uid(), user_id=user.id, title="t")
    msg_me = M.Message(id=_uid(), conversation_id=conv.id, user_id=user.id, role="user", content="hi")
    msg_ai = M.Message(id=_uid(), conversation_id=conv.id, user_id=None, role="assistant", content="yo")
    link = M.SharedLink(id=_uid(), conversation_id=conv.id, user_id=user.id, token=_uid()[:12])
    pending = M.PendingAction(id=_uid(), user_id=user.id, conversation_id=conv.id,
                              tool="design_create", args={"a": 1}, status="pending")
    blob = media / f"{m['u']}_upload.bin"
    blob.write_bytes(b"doc")
    fa = M.FileAsset(id=_uid(), user_id=user.id, conversation_id=conv.id,
                     filename="doc.pdf", mime="application/pdf", path=str(blob), size_bytes=3)
    d_file = f"{_uid()}_d.png"
    d_prt = f"{_uid()}_dp.png"
    (media / d_file).write_bytes(b"pngweb")
    (media / d_prt).write_bytes(b"pngprint")
    design = M.Design(id=_uid(), user_id=user.id, kind="flyer", idea="i", brief="b", prompt="p",
                      style="s", palette="auto", file=d_file, print_file=d_prt, width=1, height=1)
    f_vid, f_pos = f"{_uid()}.mp4", f"{_uid()}_p.jpg"
    (media / f_vid).write_bytes(b"mp4")
    (media / f_pos).write_bytes(b"jpg")
    film = M.Film(id=_uid(), user_id=user.id, prompt="p", scenes_json="[]", status="done",
                  progress=3, scene_count=3, scene_seconds=6, filename=f_vid, poster=f_pos)
    e_src, e_out = f"{_uid()}_src.mp4", f"{_uid()}_e.mp4"
    (media / e_src).write_bytes(b"src")
    (media / e_out).write_bytes(b"out")
    edit = M.Edit(id=_uid(), user_id=user.id, instruction="cut", src_name=e_src, out_name=e_out, status="done")
    design_order = M.DesignOrder(id=_uid(), owner_id=user.id, token=_uid()[:24], status="open")
    brand = M.BrandKit(user_id=user.id, brand_name="B", logo_design_id="")
    plugin = M.PluginConnection(id=_uid(), user_id=user.id, provider="gmail",
                                access_token_enc="enc", scopes="mail")
    device = M.Device(id=_uid(), user_id=user.id, platform="android", token="t")
    usage = M.UsageEvent(id=_uid(), user_id=user.id, kind="design", model="batch", tokens_in=0)
    sub = M.Subscription(id=_uid(), user_id=user.id, status="active")
    dom = M.Domain(id=_uid(), user_id=user.id, domain="x.example", kind="connect")
    other_member = _mk_user("mate@example.com")
    ws = M.Workspace(id=_uid(), owner_id=user.id, name="Crew")
    mem = M.WorkspaceMember(id=_uid(), workspace_id=ws.id, user_id=user.id, role="owner")
    mem2 = M.WorkspaceMember(id=_uid(), workspace_id=ws.id, user_id=other_member.id, role="member")
    ws_conv = M.Conversation(id=_uid(), user_id=user.id, workspace_id=ws.id, title="team chat")
    ws_msg = M.Message(id=_uid(), conversation_id=ws_conv.id, user_id=user.id, role="user", content="team msg")
    invite = M.WorkspaceInvite(id=_uid(), workspace_id=ws.id, created_by=user.id, token=_uid()[:12])
    return {"rows": [conv, msg_me, msg_ai, link, pending, fa, design, film, edit, design_order,
                     brand, plugin, device, usage, sub, dom, other_member, ws, mem, mem2,
                     ws_conv, ws_msg, invite],
            "media": [blob, media / d_file, media / d_prt, media / f_vid, media / f_pos,
                      media / e_src, media / e_out],
            "owned_ws": ws.id, "mate": other_member.id}


def test_delete_user_data_purges_everything(session):
    factory, media = session
    user = _mk_user("gone@example.com")
    seeded = _seed_everything(user, media)

    async def go():
        async with factory() as db:
            db.add(user)
            db.add(seeded["rows"][16])     # the other member (a user) first
            await db.commit()
            db.add(seeded["rows"][17])     # owned workspace next (team chat FKs to it)
            await db.commit()
            db.add_all(seeded["rows"][:16] + seeded["rows"][18:])
            await db.commit()
            summary = await acct.delete_user_data(db, user)
            # user gone, every owned table empty
            assert await db.get(M.User, user.id) is None
            for model, col in ((M.Conversation, M.Conversation.user_id), (M.Message, M.Message.user_id),
                               (M.SharedLink, M.SharedLink.user_id), (M.PendingAction, M.PendingAction.user_id),
                               (M.FileAsset, M.FileAsset.user_id), (M.Design, M.Design.user_id),
                               (M.Film, M.Film.user_id), (M.Edit, M.Edit.user_id),
                               (M.DesignOrder, M.DesignOrder.owner_id), (M.BrandKit, M.BrandKit.user_id),
                               (M.PluginConnection, M.PluginConnection.user_id), (M.Device, M.Device.user_id),
                               (M.UsageEvent, M.UsageEvent.user_id), (M.Subscription, M.Subscription.user_id),
                               (M.Domain, M.Domain.user_id), (M.WorkspaceMember, M.WorkspaceMember.user_id)):
                n = (await db.execute(select(func.count(col)).where(col == user.id))).scalar()
                assert n == 0, f"{model.__tablename__} still owns rows"
            # owned team dissolved: workspace, its chat, the invite — the other member untouched
            assert await db.get(M.Workspace, seeded["owned_ws"]) is None
            assert (await db.execute(select(M.Conversation).where(M.Conversation.workspace_id == seeded["owned_ws"]))).first() is None
            assert (await db.execute(select(M.WorkspaceInvite).where(M.WorkspaceInvite.workspace_id == seeded["owned_ws"]))).first() is None
            assert await db.get(M.User, seeded["mate"]) is not None
            assert summary["teams_dissolved"] == 1 and summary["files_removed"] == 7
        return summary

    summary = asyncio.run(go())
    for p in seeded["media"]:
        assert not p.exists(), f"{p} wasn't unlinked"
    assert summary["conversations_removed"] == 2


def test_delete_isolates_other_users(session):
    factory, media = session
    keep = _mk_user("stay@example.com")
    gone = _mk_user("gone@example.com")
    keep_conv = M.Conversation(id=_uid(), user_id=keep.id, title="mine")
    keep_msg = M.Message(id=_uid(), conversation_id=keep_conv.id, user_id=keep.id, role="user", content="keep me")
    keep_design = M.Design(id=_uid(), user_id=keep.id, kind="logo", idea="i", brief="b", prompt="p",
                           style="s", palette="auto", file="nope_d.png", print_file="nope_dp.png",
                           width=1, height=1)
    gone_conv = M.Conversation(id=_uid(), user_id=gone.id, title="theirs")

    async def go():
        async with factory() as db:
            db.add_all([keep, gone])
            await db.commit()
            db.add_all([keep_conv, keep_msg, keep_design, gone_conv])
            await db.commit()
            await acct.delete_user_data(db, gone)
            assert await db.get(M.User, keep.id) is not None
            assert await db.get(M.Conversation, keep_conv.id) is not None
            assert await db.get(M.Message, keep_msg.id) is not None
            assert await db.get(M.Design, keep_design.id) is not None
            assert await db.get(M.Conversation, gone_conv.id) is None

    asyncio.run(go())


def test_collect_user_media_basename_guard(session):
    factory, media = session
    user = _mk_user("careful@example.com")
    evil = M.Design(id=_uid(), user_id=user.id, kind="flyer", idea="i", brief="b", prompt="p",
                    style="s", palette="auto", file="../../etc/passwd", print_file="ok_dp.png",
                    width=1, height=1)

    async def go():
        async with factory() as db:
            db.add(user)
            await db.commit()
            db.add(evil)
            await db.commit()
            paths = await acct.collect_user_media(db, user.id)
            names = [p.name for p in paths]
            assert "passwd" not in names
            assert str(media / "ok_dp.png") in [str(p) for p in paths]

    asyncio.run(go())
