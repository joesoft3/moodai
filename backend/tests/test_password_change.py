"""v1.8.0 — 🔑 self-service change-password: current-password gate, no-op
rejection, full rotate cycle (old login dies, new login works), auth required."""

import asyncio

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_db
from app.main import app

EMAIL = "rotate.me@moodaiapp.com"
OLD = "OldPass-2026!"
NEW = "NewPass-2026#strong"


@pytest.fixture()
def env():
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
    yield factory
    app.dependency_overrides.pop(get_db, None)
    asyncio.run(engine.dispose())


def _run(coro):
    return asyncio.run(coro)


async def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _register(c):
    r = await c.post("/api/v1/auth/register", json={"email": EMAIL, "password": OLD, "name": "Rotate"})
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def test_change_requires_auth(env):
    _run(_test_change_requires_auth())


async def _test_change_requires_auth():
    async with await _client() as c:
        r = await c.post("/api/v1/auth/change-password",
                         json={"current_password": OLD, "new_password": NEW})
        assert r.status_code in (401, 403)


def test_change_wrong_current_rejected(env):
    _run(_test_change_wrong_current_rejected())


async def _test_change_wrong_current_rejected():
    async with await _client() as c:
        tk = await _register(c)
        h = {"Authorization": f"Bearer {tk}"}
        r = await c.post("/api/v1/auth/change-password",
                         json={"current_password": "nope-nope-nope", "new_password": NEW}, headers=h)
        assert r.status_code == 401
        assert "didn't match" in r.json()["detail"]
        # password untouched — old login still works
        r2 = await c.post("/api/v1/auth/login", json={"email": EMAIL, "password": OLD})
        assert r2.status_code == 200


def test_change_noop_rejected(env):
    _run(_test_change_noop_rejected())


async def _test_change_noop_rejected():
    async with await _client() as c:
        tk = await _register(c)
        r = await c.post("/api/v1/auth/change-password",
                         json={"current_password": OLD, "new_password": OLD},
                         headers={"Authorization": f"Bearer {tk}"})
        assert r.status_code == 400
        assert "differ" in r.json()["detail"]


def test_change_weak_new_rejected(env):
    _run(_test_change_weak_new_rejected())


async def _test_change_weak_new_rejected():
    async with await _client() as c:
        tk = await _register(c)
        r = await c.post("/api/v1/auth/change-password",
                         json={"current_password": OLD, "new_password": "short"},
                         headers={"Authorization": f"Bearer {tk}"})
        assert r.status_code == 422


def test_full_rotate_cycle(env):
    """happy path: change → old login 401, new login 200, session token stays valid."""
    _run(_test_full_rotate_cycle())


async def _test_full_rotate_cycle():
    async with await _client() as c:
        tk = await _register(c)
        h = {"Authorization": f"Bearer {tk}"}
        r = await c.post("/api/v1/auth/change-password",
                         json={"current_password": OLD, "new_password": NEW}, headers=h)
        assert r.status_code == 200 and r.json()["ok"] is True
        # existing session (stateless JWT) keeps working
        me = await c.get("/api/v1/auth/me", headers=h)
        assert me.status_code == 200 and me.json()["email"] == EMAIL
        # old password dead, new password alive
        old_login = await c.post("/api/v1/auth/login", json={"email": EMAIL, "password": OLD})
        new_login = await c.post("/api/v1/auth/login", json={"email": EMAIL, "password": NEW})
        assert old_login.status_code == 401
        assert new_login.status_code == 200 and new_login.json()["access_token"]


def test_second_rotation_from_new_current(env):
    """rotation is repeatable: after one change, the NEXT change must use the new password."""
    _run(_test_second_rotation())


async def _test_second_rotation():
    async with await _client() as c:
        tk = await _register(c)
        h = {"Authorization": f"Bearer {tk}"}
        await c.post("/api/v1/auth/change-password",
                     json={"current_password": OLD, "new_password": NEW}, headers=h)
        # using the ORIGINAL password as 'current' must now fail
        r = await c.post("/api/v1/auth/change-password",
                         json={"current_password": OLD, "new_password": "ThirdPass-2026!"}, headers=h)
        assert r.status_code == 401
        # using the CURRENT one succeeds
        r2 = await c.post("/api/v1/auth/change-password",
                          json={"current_password": NEW, "new_password": "ThirdPass-2026!"}, headers=h)
        assert r2.status_code == 200
