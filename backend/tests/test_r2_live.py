"""v1.6.0 — LIVE S3-protocol integration: upload → bucket roundtrip → 307
presigned download → byte check → delete, against a real S3 server (moto).
Skips cleanly when moto isn't installed (CI runs the stubbed unit suite).
Run locally:  pip install "moto[server]" && pytest tests/test_r2_live.py
"""

import asyncio
import shutil
import subprocess
import time

import httpx
import pytest

PORT = 5099
ENDPOINT = f"http://127.0.0.1:{PORT}"


@pytest.fixture(scope="module")
def moto():
    if shutil.which("moto_server") is None:
        pytest.skip("moto not installed (local live-integration test only)")
    proc = subprocess.Popen(
        ["moto_server", "-p", str(PORT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            httpx.get(ENDPOINT, timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    else:
        proc.terminate()
        pytest.skip("moto server failed to start")
    yield ENDPOINT
    proc.terminate()


def test_upload_download_delete_through_real_s3(moto, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from app.config import settings
    from app.db.models import Base, FileAsset
    from app.db.session import get_db
    from app.main import app
    from app.services import storage

    # point storage at the live S3 server
    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", "test-acct")
    monkeypatch.setattr(settings, "R2_ACCESS_KEY_ID", "ak")
    monkeypatch.setattr(settings, "R2_SECRET_ACCESS_KEY", "sk")
    monkeypatch.setattr(settings, "R2_BUCKET", "moodai-live")
    monkeypatch.setattr(settings, "R2_ENDPOINT_URL", moto)
    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", "")
    monkeypatch.setattr(storage, "_client", None)  # rebuild client against moto

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def _make():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_make())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _db():
        async with factory() as s:
            yield s

    async def _flow():
        # create bucket with neutral region (moto rejects R2's "auto" on this op;
        # object ops below still go through the storage client's own config)
        import boto3

        boto3.client(
            "s3", endpoint_url=moto, aws_access_key_id="ak",
            aws_secret_access_key="sk", region_name="us-east-1",
        ).create_bucket(Bucket="moodai-live")
        app.dependency_overrides[get_db] = _db
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                r = await client.post("/api/v1/auth/register", json={
                    "email": "r2live@moodaiapp.com", "password": "R2LivePass1", "display_name": "R2",
                })
                assert r.status_code in (200, 201), r.text[:120]
                H = {"Authorization": f"Bearer {r.json()['access_token']}"}

                up = await client.post(
                    "/api/v1/files",
                    files={"file": ("pic.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png")},
                    headers=H,
                )
                assert up.status_code == 201, up.text[:200]
                fid = up.json()["id"]

                async with factory() as s:
                    asset = await s.get(FileAsset, fid)
                assert asset.path.startswith("r2:uploads/"), asset.path
                key = asset.path[3:]
                obj = storage._s3().get_object(Bucket="moodai-live", Key=key)
                assert obj["Body"].read().startswith(b"\x89PNG")

                d = await client.get(
                    f"/api/v1/files/{fid}/download", headers=H, follow_redirects=False
                )
                assert d.status_code == 307
                assert "127.0.0.1:5099" in d.headers["location"]

                body = httpx.get(d.headers["location"], timeout=5)
                assert body.content.startswith(b"\x89PNG")

                dl = await client.delete(f"/api/v1/files/{fid}", headers=H)
                assert dl.status_code == 204
                assert storage._s3().list_objects_v2(Bucket="moodai-live").get("Contents", []) == []
        finally:
            app.dependency_overrides.pop(get_db, None)

    asyncio.run(_flow())
    asyncio.run(engine.dispose())
    print("\nLIVE S3 roundtrip verified ✓ (upload→bucket→presigned 307→bytes→delete)")
