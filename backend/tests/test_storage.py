"""v1.5.0 — 📦 storage layer: local default + Cloudflare R2 backend (stubbed S3)."""

import asyncio
import io
import os

import pytest

from app.config import settings
from app.services import storage


class _StubBody:
    def __init__(self, data: bytes):
        self._d = data

    def read(self):
        return self._d


class _StubS3:
    """In-memory stand-in for boto3's S3 client (bucket 'moodai')."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[Key] = Body
        return {}

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise RuntimeError("NoSuchKey")
        return {"Body": _StubBody(self.objects[Key])}

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)
        return {}

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://signed.example/{Params['Key']}?exp={ExpiresIn}"


def _r2_env(monkeypatch, stub=None):
    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", "acc123")
    monkeypatch.setattr(settings, "R2_ACCESS_KEY_ID", "ak")
    monkeypatch.setattr(settings, "R2_SECRET_ACCESS_KEY", "sk")
    monkeypatch.setattr(settings, "R2_BUCKET", "moodai")
    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", "")
    monkeypatch.setattr(storage, "_client", stub if stub is not None else _StubS3())


def test_local_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", "")
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    assert storage.r2_configured() is False
    path = asyncio.run(storage.put_upload("u1", "My Photo!.png", b"PNGBYTES"))
    assert path.startswith(str(tmp_path)) and "My_Photo_.png" in path
    assert asyncio.run(storage.read_bytes(path)) == b"PNGBYTES"
    assert asyncio.run(storage.delete(path)) is True
    assert asyncio.run(storage.read_bytes(path)) is None


def test_r2_marker_roundtrip(monkeypatch):
    stub = _StubS3()
    _r2_env(monkeypatch, stub)
    assert storage.r2_configured() is True
    path = asyncio.run(storage.put_upload("u1", "doc.pdf", b"PDF"))
    assert path.startswith("r2:uploads/u1/")
    assert stub.objects[path[3:]] == b"PDF"
    assert asyncio.run(storage.read_bytes(path)) == b"PDF"
    url = asyncio.run(storage.presigned_url(path, seconds=99))
    assert url.startswith("https://signed.example/") and "exp=99" in url
    assert asyncio.run(storage.delete(path)) is True
    assert stub.objects == {}


def test_r2_public_base_beats_presign(monkeypatch):
    _r2_env(monkeypatch, _StubS3())
    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com")
    url = asyncio.run(storage.presigned_url("r2:uploads/u1/x.png"))
    assert url == "https://cdn.example.com/uploads/u1/x.png"


def test_mixed_backends_independent(monkeypatch, tmp_path):
    """Local rows stay local when R2 turns on (the coexistence contract)."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", "")
    local_path = asyncio.run(storage.put_upload("u1", "a.txt", b"local"))
    _r2_env(monkeypatch, _StubS3())
    assert storage.is_remote(local_path) is False
    assert asyncio.run(storage.read_bytes(local_path)) == b"local"
    remote_path = asyncio.run(storage.put_upload("u1", "b.txt", b"remote"))
    assert storage.is_remote(remote_path) is True
    assert asyncio.run(storage.delete(local_path)) is True


def test_missing_keys_fail_soft(monkeypatch):
    _r2_env(monkeypatch, _StubS3())
    assert asyncio.run(storage.read_bytes("r2:uploads/ghost/none.bin")) is None
    assert asyncio.run(storage.read_bytes("/no/such/local.bin")) is None
