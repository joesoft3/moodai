"""v1.9.7 — 🎨🎬 in-chat creation SSE contract: meta → media_start → (progress) →
media → done, assistant row persisted with meta.media, plain chat untouched."""

import asyncio
import json

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes import chat as chatmod
from app.config import settings
from app.db.models import Base, Message
from app.db.session import get_db
from app.main import app

EMAIL = "creator@moodaiapp.com"
PW = "Create-2026!"


def _parse_sse(body: str) -> list[dict]:
    out = []
    for chunk in body.split("\n\n"):
        line = chunk.strip()
        if line.startswith("data:"):
            try:
                out.append(json.loads(line[5:].strip()))
            except Exception:
                pass
    return out


@pytest.fixture()
def env(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    async def _make():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_make())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _db():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = _db
    # request-local SessionLocal calls inside the streamer write via the same engine
    monkeypatch.setattr(chatmod, "SessionLocal", factory)
    monkeypatch.setattr(settings, "CHAT_MEDIA", True)
    yield factory
    app.dependency_overrides.pop(get_db, None)
    asyncio.run(engine.dispose())


def run(coro):
    return asyncio.run(coro)


async def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _token(c):
    r = await c.post("/api/v1/auth/register", json={"email": EMAIL, "password": PW, "name": "Creator"})
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


async def _post_chat(c, tk, payload):
    r = await c.post(
        "/api/v1/chat/stream",
        json=payload,
        headers={"Authorization": f"Bearer {tk}"},
    )
    assert r.status_code == 200, r.text
    return _parse_sse(r.text)


# ---------------------------------------------------------------- image flow
def test_image_flow_sse_contract(env, monkeypatch):
    async def fake_image(prompt, **opts):
        assert "kente robot" in prompt
        return "https://provider.example/gen.png"

    async def fake_persist(db, user, url):
        return "https://cdn.example/archived.png", "r2"

    monkeypatch.setattr(chatmod.llm, "generate_image", fake_image)
    monkeypatch.setattr(chatmod, "_persist_generated_image", fake_persist)

    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            evs = await _post_chat(c, tk, {
                "conversation_id": None, "message": "create an image of a kente robot waving",
                "files": [], "search": False,
            })
            types = [e.get("type") for e in evs]
            assert types[0] == "meta"
            assert "media_start" in types and "media" in types and types[-1] == "done"
            start = next(e for e in evs if e["type"] == "media_start")
            assert start["kind"] == "image" and "kente robot" in start["prompt"]
            media = next(e for e in evs if e["type"] == "media")
            assert media["url"] == "https://cdn.example/archived.png" and media["stored"] == "r2"
            meta = evs[0]
            assert meta["model"] == "Mood Canvas"  # friendly label only — no vendor names
            # assistant persisted with meta.media (reload contract)
            async with env() as s:
                from sqlalchemy import select
                rows = (await s.execute(select(Message).where(Message.role == "assistant"))).scalars().all()
                assert len(rows) == 1
                m0 = rows[0].meta["media"][0]
                assert m0["kind"] == "image" and m0["url"].endswith("archived.png")
                assert rows[0].content.startswith("🎨")
                assert rows[0].meta["mode"] == "media"
            # refinement turn: "make it night time" → merged prompt, refine=True caption
            captured = {}

            async def fake_image2(prompt, **opts):
                captured["prompt"] = prompt
                return "https://provider.example/gen2.png"

            monkeypatch.setattr(chatmod.llm, "generate_image", fake_image2)
            evs2 = await _post_chat(c, tk, {
                "conversation_id": meta["conversation_id"], "message": "make it night time",
                "files": [], "search": False,
            })
            assert any(e["type"] == "media" for e in evs2)
            assert "kente robot" in captured["prompt"] and "night time" in captured["prompt"]
            async with env() as s:
                from sqlalchemy import select
                rows = (await s.execute(
                    select(Message).where(Message.role == "assistant").order_by(Message.created_at)
                )).scalars().all()
                assert rows[-1].content.startswith("🎨 **Remixed it**")

    run(_t())


def test_image_provider_failure_is_friendly(env, monkeypatch):
    async def boom(prompt, **opts):
        raise RuntimeError("quota storm")

    monkeypatch.setattr(chatmod.llm, "generate_image", boom)

    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            evs = await _post_chat(c, tk, {
                "conversation_id": None, "message": "paint a sunset over Cape Coast",
                "files": [], "search": False,
            })
            err = [e for e in evs if e["type"] == "error"]
            assert err, evs
            assert "quota storm" not in err[0]["message"]  # friendly, never raw internals

    run(_t())


# ---------------------------------------------------------------- video flow
def test_video_flow_sse_contract(env, monkeypatch):
    async def fake_video(prompt, opts, image=None, on_progress=None):
        assert opts.aspect_ratio in ("16:9", "9:16", "1:1")
        if on_progress:
            on_progress({"stage": "scenes", "done": 0, "total": 3})
            on_progress({"stage": "scenes", "done": 3, "total": 3})
            on_progress({"stage": "compositing", "done": 1, "total": 1})
        return "https://media.example/reel.mp4", False

    async def fake_persist_media(db, user, url, expect):
        assert expect == "video"
        return "https://cdn.example/reel.mp4", "r2"

    monkeypatch.setattr(chatmod.video, "generate", fake_video)
    monkeypatch.setattr(chatmod, "_persist_generated_media", fake_persist_media)

    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            evs = await _post_chat(c, tk, {
                "conversation_id": None, "message": "make a video of waves crashing at Labadi beach",
                "files": [], "search": False,
            })
            types = [e.get("type") for e in evs]
            assert "media_start" in types and "media" in types and types[-1] == "done"
            prog = [e for e in evs if e["type"] == "media_progress"]
            assert len(prog) == 3 and prog[0]["stage"] == "scenes" and prog[-1]["done"] == 1
            media = next(e for e in evs if e["type"] == "media")
            assert media["kind"] == "video" and media["url"].endswith("reel.mp4")
            assert evs[0]["model"] == "Mood Reel"
            async with env() as s:
                from sqlalchemy import select
                rows = (await s.execute(select(Message).where(Message.role == "assistant"))).scalars().all()
                assert rows[0].meta["media"][0]["kind"] == "video"
                assert rows[0].content.startswith("🎬")

    run(_t())


def test_video_aspect_hint_vertical(env, monkeypatch):
    seen = {}

    async def fake_video(prompt, opts, image=None, on_progress=None):
        seen["aspect"] = opts.aspect_ratio
        seen["style"] = opts.style
        return "https://media.example/v.mp4", False

    monkeypatch.setattr(chatmod.video, "generate", fake_video)

    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            await _post_chat(c, tk, {
                "conversation_id": None, "message": "create a vertical anime video of a tro-tro at night",
                "files": [], "search": False,
            })
            assert seen["aspect"] == "9:16" and seen["style"] == "anime"

    run(_t())


# -------------------------------------------------------------- mode forcing
def test_mode_field_forces_kind(env, monkeypatch):
    async def fake_image(prompt, **opts):
        return "https://provider.example/x.png"

    monkeypatch.setattr(chatmod.llm, "generate_image", fake_image)

    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            # message has no creation keywords — mode="image" must force it
            evs = await _post_chat(c, tk, {
                "conversation_id": None, "message": "a lighthouse at dawn",
                "files": [], "search": False, "mode": "image",
            })
            assert any(e["type"] == "media" and e["kind"] == "image" for e in evs)

    run(_t())


# -------------------------------------------------------------- untouched
def test_plain_chat_not_media_routed(env, monkeypatch):
    async def no_stream(*a, **k):
        yield {"type": "delta", "text": "hello there"}

    monkeypatch.setattr(chatmod.llm, "stream_chat", no_stream)

    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            evs = await _post_chat(c, tk, {
                "conversation_id": None, "message": "what is the capital of Ghana?",
                "files": [], "search": False,
            })
            assert not any(e["type"].startswith("media") for e in evs)
            assert any(e["type"] == "delta" and "hello" in e.get("text", "") for e in evs)

    run(_t())


def test_kill_switch_off(env, monkeypatch):
    monkeypatch.setattr(settings, "CHAT_MEDIA", False)

    async def no_stream(*a, **k):
        yield {"type": "delta", "text": "ok"}

    monkeypatch.setattr(chatmod.llm, "stream_chat", no_stream)

    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            evs = await _post_chat(c, tk, {
                "conversation_id": None, "message": "create an image of a goat",
                "files": [], "search": False,
            })
            assert not any(e["type"] == "media" for e in evs)

    run(_t())


# ------------------------------------------------- self-hosted media persist
def test_persist_video_reads_self_hosted_from_disk(monkeypatch, tmp_path):
    """Sibling-machine race regression: /api/v1/media/files/*.mp4 must be read
    from local MEDIA_DIR, not via loopback HTTP that can 404 on a peer."""
    import asyncio as _a

    from app.api.routes import chat as chatmod
    from app.services import storage

    clip = tmp_path / "reel-deadbeef.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42CLIPBYTES")
    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "IMAGE_PERSIST", True)

    class _DB:
        def __init__(self):
            self.rows = []
            self.committed = 0

        def add(self, r):
            self.rows.append(r)

        async def commit(self):
            self.committed += 1

    class _User:
        id = "u1"

    async def _put(user_id, filename, data):
        assert data.startswith(b"\x00\x00\x00\x18ftypmp42")
        return f"r2:gallery/{filename}"

    async def _presign(marker, seconds=None):
        return "https://signed.example/clip.mp4"

    def _no_http(**kw):  # must NEVER loopback-fetch self-hosted files
        raise AssertionError("loopback GET attempted for self-hosted media")

    monkeypatch.setattr(storage, "put_upload", _put)
    monkeypatch.setattr(storage, "presigned_url", _presign)
    monkeypatch.setattr(storage, "is_remote", lambda marker: marker.startswith("r2:"))
    monkeypatch.setattr(chatmod.httpx, "AsyncClient", _no_http)

    url, stored = _a.run(
        chatmod._persist_generated_media(_DB(), _User(), "https://moodai-api.fly.dev/api/v1/media/files/reel-deadbeef.mp4", "video")
    )
    assert stored == "r2" and url == "https://signed.example/clip.mp4"


def test_persist_video_sibling_404_no_longer_possible(monkeypatch, tmp_path):
    """The exact live failure shape: file missing here → clean hotlink fallback."""
    import asyncio as _a

    from app.api.routes import chat as chatmod

    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))  # empty — file landed on a sibling
    monkeypatch.setattr(settings, "IMAGE_PERSIST", True)

    class _DB:
        def add(self, r):
            pass

        async def commit(self):
            pass

    class _User:
        id = "u1"

    url, stored = _a.run(
        chatmod._persist_generated_media(_DB(), _User(), "https://moodai-api.fly.dev/api/v1/media/files/reel-gone.mp4", "video")
    )
    assert stored == "hotlink" and url.endswith("reel-gone.mp4")
