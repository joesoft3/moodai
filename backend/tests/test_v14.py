"""v1.3.1 — ▲ Vercel serverless readiness.

Covers: writable-dir relocation on ephemeral hosts, ffmpeg static fallback,
bundled font, embeddings API fallback, dependency split (slim vs full),
and the serverless entry point itself.
"""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app.config import Settings, settings
from app.services import designer, memory, soundtrack

ROOT = Path(__file__).resolve().parents[1]  # backend/


# ------------------------------------------------------------------ settings
def test_serverless_relocates_writable_dirs(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("UPLOAD_DIR", raising=False)
    monkeypatch.delenv("MOOD_SERVERLESS", raising=False)
    s = Settings(_env_file=None)
    assert s.serverless is True
    assert s.UPLOAD_DIR == "/tmp/mood-uploads"


def test_serverless_flag_via_mood_serverless(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.setenv("MOOD_SERVERLESS", "1")
    s = Settings(_env_file=None)
    assert s.serverless is True
    assert s.UPLOAD_DIR == "/tmp/mood-uploads"


def test_explicit_upload_dir_survives_relocation(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("UPLOAD_DIR", "/data/storage")
    monkeypatch.delenv("MOOD_SERVERLESS", raising=False)
    s = Settings(_env_file=None)
    assert s.UPLOAD_DIR == "/data/storage"


def test_not_serverless_by_default(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("MOOD_SERVERLESS", raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    s = Settings(_env_file=None)
    assert s.serverless is False
    assert s.UPLOAD_DIR == "./storage"


# -------------------------------------------------------------------- ffmpeg
def test_ffmpeg_static_fallback(monkeypatch):
    monkeypatch.setattr(soundtrack.shutil, "which", lambda _name: None)
    monkeypatch.setattr(settings, "FFMPEG_PATH", "ffmpeg")
    monkeypatch.setattr(soundtrack.os.path, "exists", lambda p: True)

    class _FakeIio:
        @staticmethod
        def get_ffmpeg_exe():
            return "/opt/bundle/ffmpeg"

    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", _FakeIio)
    assert soundtrack.ffmpeg_path() == "/opt/bundle/ffmpeg"


def test_ffmpeg_none_when_nothing_available(monkeypatch):
    monkeypatch.setattr(soundtrack.shutil, "which", lambda _name: None)
    monkeypatch.setattr(settings, "FFMPEG_PATH", "ffmpeg")
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", None)  # import raises ImportError
    assert soundtrack.ffmpeg_path() is None


def test_ffmpeg_explicit_path_honored(monkeypatch):
    monkeypatch.setattr(settings, "FFMPEG_PATH", __file__)  # any existing file
    assert soundtrack.ffmpeg_path() == __file__


# ---------------------------------------------------------------------- font
def test_bundled_font_is_first_choice():
    f = designer.brand_font()
    assert f is not None
    assert f.endswith("DejaVuSans-Bold.ttf")
    assert "assets" in f and Path(f).exists()


# -------------------------------------------------------------------- embed
def test_embed_local_fastembed_preferred(monkeypatch):
    monkeypatch.setattr(memory, "TextEmbedding", object)  # "installed"
    monkeypatch.setattr(memory, "_embed_sync", lambda texts: [[1.0]] * len(texts))
    vecs = asyncio.run(memory.embed(["a", "b"]))
    assert vecs == [[1.0], [1.0]]


def test_embed_api_fallback_orders_and_dims(monkeypatch):
    monkeypatch.setattr(memory, "TextEmbedding", None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "k-test")
    captured = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [
                {"index": 1, "embedding": [0.1, 0.1]},
                {"index": 0, "embedding": [0.2, 0.2]},
            ]}

    class _Client:
        def __init__(self, **kw):
            captured["kw"] = kw

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            captured["url"] = url
            captured["payload"] = json
            return _Resp()

    monkeypatch.setattr(memory.httpx, "AsyncClient", _Client)
    vecs = asyncio.run(memory.embed(["x", "y"]))
    assert vecs == [[0.2, 0.2], [0.1, 0.1]]  # sorted by provider index
    assert captured["url"] == "/embeddings"
    assert captured["payload"]["model"] == settings.EMBED_API_MODEL
    assert captured["payload"]["dimensions"] == settings.EMBED_VECTOR_SIZE
    assert captured["kw"]["headers"]["Authorization"] == "Bearer k-test"


def test_embed_unavailable_without_backends(monkeypatch):
    monkeypatch.setattr(memory, "TextEmbedding", None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    with pytest.raises(memory.EmbeddingUnavailable):
        asyncio.run(memory.embed(["x"]))


# ------------------------------------------------------- serverless entrypoint
def test_vercel_json_routes_everything_to_entry():
    cfg = json.loads((ROOT / "vercel.json").read_text())
    dests = [r["destination"] for r in cfg["rewrites"]]
    assert any(d.startswith("/api/index") for d in dests)
    assert (ROOT / "api" / "index.py").exists()


def test_api_entry_exposes_asgi_app():
    spec = importlib.util.spec_from_file_location("vercel_entry", ROOT / "api" / "index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from fastapi import FastAPI

    assert isinstance(mod.app, FastAPI)


# ------------------------------------------------------- dependency split
def test_requirements_split_keeps_slim_bundle():
    slim_pkgs = [
        ln.split(">=")[0].split("==")[0].strip().lower()
        for ln in (ROOT / "requirements.txt").read_text().splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    full = (ROOT / "requirements-full.txt").read_text()
    assert "fastembed" not in slim_pkgs  # onnxruntime stays out of the 250 MB serverless bundle
    assert "imageio-ffmpeg" in slim_pkgs  # static ffmpeg must ship in the slim bundle
    assert "fastembed" in full and "-r requirements.txt" in full
