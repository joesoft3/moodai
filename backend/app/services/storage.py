"""Durable file storage abstraction.

Backends (auto-selected):
- **local** — disk under settings.UPLOAD_DIR (dev machines, Docker volumes)
- **r2**    — Cloudflare R2 (S3-compatible) once R2_ACCOUNT_ID + keys + bucket
              are configured. Zero egress fees, no extra server to run.

DB marker convention: stored paths are either an absolute local path
("/data/storage/…") or the string "r2:<object-key>", so rows written by one
backend stay readable if the other is later enabled/disabled.
"""

import asyncio
import logging
import os
import re
import uuid

from ..config import settings

log = logging.getLogger(__name__)

PREFIX = "r2:"
_client = None


def r2_configured() -> bool:
    return bool(
        settings.R2_ACCOUNT_ID and settings.R2_ACCESS_KEY_ID and settings.R2_SECRET_ACCESS_KEY
    )


def _s3():
    """Lazy boto3 client. Default endpoint is Cloudflare R2; R2_ENDPOINT_URL
    overrides it for any S3-compatible service (MinIO, Backblaze B2, moto CI)."""
    global _client
    if _client is None:
        import boto3  # lazy: only when remote storage is actually in use

        endpoint = settings.R2_ENDPOINT_URL or (
            f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
        )
        _client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name="auto",  # R2 convention
        )
    return _client


def _key(user_id: str, filename: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename or "upload")
    return f"uploads/{user_id}/{uuid.uuid4().hex}_{safe}"


async def put_upload(user_id: str, filename: str, data: bytes) -> str:
    """Persist raw upload bytes; returns the DB-storable path marker."""
    if r2_configured():
        key = _key(user_id, filename)
        await asyncio.to_thread(
            _s3().put_object, Bucket=settings.R2_BUCKET, Key=key, Body=data
        )
        return PREFIX + key
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename or "upload")
    path = os.path.join(settings.UPLOAD_DIR, user_id, f"{uuid.uuid4().hex}_{safe}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


async def read_bytes(storage_path: str) -> bytes | None:
    """Fetch bytes back (analysis pipelines, doc extraction). None if missing."""
    if storage_path.startswith(PREFIX):
        key = storage_path[len(PREFIX):]
        try:
            obj = await asyncio.to_thread(
                _s3().get_object, Bucket=settings.R2_BUCKET, Key=key
            )
            return obj["Body"].read()
        except Exception as e:
            log.warning("r2 read failed for %s: %s", key, e)
            return None
    try:
        with open(storage_path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


async def presigned_url(storage_path: str, seconds: int | None = None) -> str | None:
    """Time-limited download URL for an r2 object. Public base wins when set."""
    if not storage_path.startswith(PREFIX):
        return None
    key = storage_path[len(PREFIX):]
    if settings.R2_PUBLIC_BASE_URL:
        return f"{settings.R2_PUBLIC_BASE_URL.rstrip('/')}/{key}"
    return await asyncio.to_thread(
        _s3().generate_presigned_url,
        "get_object",
        Params={"Bucket": settings.R2_BUCKET, "Key": key},
        ExpiresIn=seconds or settings.R2_PRESIGN_SECONDS,
    )


async def delete(storage_path: str) -> bool:
    """Delete from whichever backend the marker points at. False if nothing there."""
    if storage_path.startswith(PREFIX):
        key = storage_path[len(PREFIX):]
        try:
            await asyncio.to_thread(
                _s3().delete_object, Bucket=settings.R2_BUCKET, Key=key
            )
            return True
        except Exception as e:
            log.warning("r2 delete failed for %s: %s", key, e)
            return False
    try:
        os.unlink(storage_path)
        return True
    except OSError:
        return False


def is_remote(storage_path: str) -> bool:
    return storage_path.startswith(PREFIX)
