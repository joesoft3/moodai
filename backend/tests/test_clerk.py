"""v1.6.0 — 🔐 Clerk federation seam: JWKS-verified login, find-or-provision
by email, signup-gate respect, disabled-state, forgery rejection."""

import asyncio
import time

import httpx
import pytest
from jose import jwk, jwt
from jose.utils import base64url_encode
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.models import Base, User
from app.db.session import get_db
from app.main import app
from app.services import clerk_auth

ISS = "https://clerk.test"


def _rsa_material():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = priv.public_key().public_numbers()
    jwkd = {
        "kty": "RSA", "kid": "clerk-test-key", "use": "sig", "alg": "RS256",
        "n": base64url_encode(pub.n.to_bytes((pub.n.bit_length() + 7) // 8, "big")).decode(),
        "e": base64url_encode(pub.e.to_bytes((pub.e.bit_length() + 7) // 8, "big")).decode(),
    }
    pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return jwkd, pem


PUB_JWK, PRIV_PEM = _rsa_material()
PUB_JWK2, PRIV_PEM2 = _rsa_material()  # impostor keypair


def _token(claims: dict, pem=PRIV_PEM, kid="clerk-test-key") -> str:
    now = int(time.time())
    base = {"iss": ISS, "sub": "user_clerk_1", "iat": now - 10, "nbf": now - 10, "exp": now + 3600}
    return jwt.encode({**base, **claims}, pem, algorithm="RS256", headers={"kid": kid})


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "CLERK_ISSUER", ISS)
    monkeypatch.setattr(settings, "CLERK_AUDIENCE", "")
    monkeypatch.setattr(settings, "CLERK_SECRET_KEY", "")
    monkeypatch.setattr(clerk_auth, "_jwks_cache", {"keys": [], "fetched_at": 0})

    async def fake_jwks(force: bool = False):
        return [PUB_JWK]

    monkeypatch.setattr(clerk_auth, "_fetch_jwks", fake_jwks)

    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

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


def test_clerk_login_provisions_new_user(env):
    async def flow():
        async with await _client() as client:
            r = await client.post("/api/v1/auth/clerk", json={"token": _token({"email": "NewClerk@User.com"})})
            assert r.status_code == 200, r.text[:160]
            body = r.json()
            assert body["user"]["email"] == "newclerk@user.com"
            tok = body["access_token"]
            me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
            assert me.status_code == 200 and me.json()["email"] == "newclerk@user.com"
            return body["user"]["id"]

    uid = _run(flow())
    async def second():
        async with await _client() as client:
            r = await client.post("/api/v1/auth/clerk", json={"token": _token({"email": "newclerk@user.com"})})
            assert r.json()["user"]["id"] == uid  # same account, not a duplicate
    _run(second())


def test_clerk_email_fallback_via_backend_api(env, monkeypatch):
    async def fake_email(sub):
        assert sub == "user_clerk_9"
        return "lookup@via-api.dev"
    monkeypatch.setattr(clerk_auth, "fetch_primary_email", fake_email)

    async def flow():
        async with await _client() as client:
            claims = {"sub": "user_clerk_9"}  # no email claim at all
            r = await client.post("/api/v1/auth/clerk", json={"token": _token(claims)})
            assert r.status_code == 200
            assert r.json()["user"]["email"] == "lookup@via-api.dev"
    _run(flow())


def test_forged_token_rejected(env):
    async def flow():
        async with await _client() as client:
            forged = _token({"email": "mallory@evil.dev"}, pem=PRIV_PEM2, kid="clerk-test-key")
            r = await client.post("/api/v1/auth/clerk", json={"token": forged})
            assert r.status_code == 401
    _run(flow())


def test_expired_token_rejected(env):
    now = int(time.time())
    expired = jwt.encode(
        {"iss": ISS, "sub": "u1", "iat": now - 4000, "nbf": now - 4000, "exp": now - 3000,
         "email": "old@user.dev"},
        PRIV_PEM, algorithm="RS256", headers={"kid": "clerk-test-key"})

    async def flow():
        async with await _client() as client:
            r = await client.post("/api/v1/auth/clerk", json={"token": expired})
            assert r.status_code == 401
    _run(flow())


def test_signup_gate_blocks_new_federated_users(env, monkeypatch):
    from app.api.routes import auth as auth_routes

    async def closed(_db):
        return False
    monkeypatch.setattr(auth_routes, "signup_open", closed)

    async def flow():
        async with await _client() as client:
            r = await client.post("/api/v1/auth/clerk", json={"token": _token({"email": "fresh@face.dev"})})
            assert r.status_code == 403 and "Signups are closed" in r.json()["detail"]
    _run(flow())


def test_disabled_until_configured(env, monkeypatch):
    monkeypatch.setattr(settings, "CLERK_ISSUER", "")

    async def flow():
        async with await _client() as client:
            r = await client.post("/api/v1/auth/clerk", json={"token": _token({"email": "x@y.dev"})})
            assert r.status_code == 404
    _run(flow())
