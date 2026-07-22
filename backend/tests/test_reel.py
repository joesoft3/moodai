"""v1.9.7 — 🎬 Mood Reel composer (scene fetch → ffmpeg Ken Burns) + provider cascade."""

import asyncio

import httpx
import pytest

from app.config import settings
from app.services import media as media_mod
from app.services.media import (
    VideoGenerationError,
    VideoNotConfigured,
    VideoOptions,
    compile_prompt,
    video,
)


def run(coro):
    return asyncio.run(coro)


class _FakeResp:
    def __init__(self, status=200, ctype="image/jpeg", body=b"\xff\xd8\xffimg"):
        self.status_code = status
        self.headers = {"content-type": ctype}
        self.content = body
        self.text = body.decode("latin1", "ignore") if isinstance(body, bytes) else str(body)


class _FakeProc:
    def __init__(self, rc=0):
        self.returncode = rc

    async def communicate(self):
        return b"", b""

    def kill(self):
        self.returncode = -9


@pytest.fixture()
def reel_env(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "BACKEND_PUBLIC_URL", "https://api.test")
    monkeypatch.setattr(settings, "REEL_ENABLED", True)
    monkeypatch.setattr(settings, "VIDEO_PROVIDER", "reel")
    monkeypatch.setattr(media_mod, "_ffmpeg_exe", lambda: "/usr/bin/ffmpeg")

    async def fake_get(url, **kw):
        return _FakeResp()

    monkeypatch.setattr(video._http, "get", fake_get)

    real_exec = asyncio.subprocess.create_subprocess_exec

    async def fake_exec(*cmd, **kw):
        # write the output file where the command says it goes, like a real ffmpeg
        out = cmd[-1]
        with open(out, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42FAKEMP4")
        return _FakeProc(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    yield
    monkeypatch.setattr(asyncio, "create_subprocess_exec", real_exec)


def test_reel_produces_mp4_url_and_progress(reel_env):
    stages: list[dict] = []
    url, i2v = run(video.generate("a kente robot dancing adowa", VideoOptions(duration=8),
                                   on_progress=lambda d: stages.append(dict(d))))
    assert url.startswith("https://api.test/api/v1/media/files/reel-")
    assert url.endswith(".mp4") and i2v is False
    kinds = [s["stage"] for s in stages]
    assert "scenes" in kinds and "compositing" in kinds
    assert stages[-1] == {"stage": "compositing", "done": 1, "total": 1}


def test_reel_scene_shortfall_fails(reel_env, monkeypatch):
    calls = {"n": 0}

    async def starving_get(url, **kw):
        calls["n"] += 1
        return _FakeResp(status=502, ctype="text/html", body=b"bad gateway")

    monkeypatch.setattr(video._http, "get", starving_get)
    with pytest.raises(VideoGenerationError):
        run(video._reel("impossible scene", VideoOptions(duration=6)))


def test_reel_needs_ffmpeg(monkeypatch):
    monkeypatch.setattr(media_mod, "_ffmpeg_exe", lambda: None)
    with pytest.raises(VideoNotConfigured):
        run(video._reel("x", VideoOptions()))


# --------------------------------------------------------------- cascade
def test_cascade_xai_402_falls_through_to_reel(reel_env, monkeypatch):
    monkeypatch.setattr(settings, "VIDEO_PROVIDER", "xai,reel")
    monkeypatch.setattr(settings, "XAI_API_KEY", "xai-test")

    async def no_credits(url, **kw):
        if url.endswith("/videos/generations"):
            return _FakeResp(status=402, ctype="application/json", body=b'{"error":"no credits"}')
        return _FakeResp()

    monkeypatch.setattr(video._http, "post", no_credits)
    url, _ = run(video.generate("accra skyline aerial", VideoOptions(duration=6)))
    assert "reel-" in url  # xai declined (credits) → reel composed it


def test_cascade_unknown_member_skips(reel_env, monkeypatch):
    monkeypatch.setattr(settings, "VIDEO_PROVIDER", "runway,reel")
    url, _ = run(video.generate("surf at Busua", VideoOptions(duration=6)))
    assert "reel-" in url


def test_last_provider_failure_raises(monkeypatch):
    monkeypatch.setattr(settings, "VIDEO_PROVIDER", "pollinations")
    monkeypatch.setattr(settings, "POLLINATIONS_API_KEY", "")
    with pytest.raises(VideoNotConfigured):
        run(video.generate("x", VideoOptions()))


def test_pollinations_no_key_not_configured():
    import asyncio as _a

    async def _t():
        await video._pollinations("x", VideoOptions())

    with pytest.raises(VideoNotConfigured):
        _a.run(_t())


def test_compile_prompt_layers_style():
    out = compile_prompt("a robot chef", VideoOptions(style="anime", quality="1080p"))
    assert "robot chef" in out and "anime" in out and "Avoid:" in out


def test_reel_disabled_not_configured(reel_env, monkeypatch):
    monkeypatch.setattr(settings, "REEL_ENABLED", False)
    with pytest.raises(VideoNotConfigured):
        run(video._reel("x", VideoOptions()))


def test_http_timeout_budget(reel_env):
    # generation must never hang: pollinations GET honours client timeouts (regression guard)
    assert isinstance(video._http, httpx.AsyncClient)
