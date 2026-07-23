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


def test_reel_solo_scene_rescue_clones(reel_env, monkeypatch):
    """Vercel lesson (live): provider may shed all-but-one scene fetch — a single
    good frame must still compose a reel (mirrored clone), never a dead stream."""
    calls = {"n": 0}

    async def one_good_fetch(url, **kw):
        calls["n"] += 1
        seed_hit = "seed=" in url and url.split("seed=")[1].split("&")[0]
        # deterministic: only the FIRST scene render succeeds, the rest shed
        return _FakeResp() if calls["n"] == 1 else _FakeResp(status=429, ctype="application/json", body=b'{"error":"slow down"}')

    monkeypatch.setattr(video._http, "get", one_good_fetch)
    stages: list[dict] = []
    url, _ = run(video.generate("a solo frame rescue", VideoOptions(duration=6),
                                on_progress=lambda d: stages.append(dict(d))))
    assert "reel-" in url and url.endswith(".mp4")
    assert any(s["stage"] == "compositing" for s in stages)


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


# ================================================== v1.9.8 richer reels
class _JsonResp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status
        self.text = jsonlib.dumps(payload)
        self.headers = {"content-type": "application/json"}
        self.content = self.text.encode()

    def json(self):
        return self._p


import json as jsonlib


@pytest.fixture()
def rich_env(reel_env, monkeypatch):
    """Scenes fetched + storyboard + TTS off by default; tests toggle pieces."""
    monkeypatch.setattr(settings, "EXTRA_BRAIN_API_KEY", "")
    monkeypatch.setattr(settings, "EMBED_API_KEY", "")
    monkeypatch.setattr(settings, "EMBED_API_BASE_URL", "")
    monkeypatch.setattr(settings, "REEL_STORYBOARD", True)
    monkeypatch.setattr(settings, "REEL_NARRATION", True)
    return


def test_storyboard_parses_scenes_and_narration(rich_env, monkeypatch):
    payload = {
        "choices": [{
            "message": {"content": '{"scenes": ["wide kente loom detail", "hands threading gold", "finished cloth in sunlight"], "narration": "Woven by hand, worn with pride."}'}
        }]
    }

    async def fake_post(url, **kw):
        assert "groq.com" in url
        return _JsonResp(payload)

    monkeypatch.setattr(settings, "EXTRA_BRAIN_API_KEY", "gsk-test")
    monkeypatch.setattr(settings, "EXTRA_BRAIN_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setattr(video._http, "post", fake_post)
    scenes, narration = run(video._storyboard("kente weaving", 3))
    assert scenes and len(scenes) == 3 and "loom" in scenes[0]
    assert narration == "Woven by hand, worn with pride."


def test_storyboard_bad_json_falls_back(rich_env, monkeypatch):
    async def fake_post(url, **kw):
        return _JsonResp({"choices": [{"message": {"content": "sorry, cannot help with that"}}]})

    monkeypatch.setattr(settings, "EXTRA_BRAIN_API_KEY", "gsk-test")
    monkeypatch.setattr(video._http, "post", fake_post)
    assert run(video._storyboard("x", 3)) == (None, None)


def test_storyboard_no_key_falls_back(rich_env):
    assert run(video._storyboard("kente", 3)) == (None, None)


def test_narrate_cascade_all_fail_returns_none(rich_env, monkeypatch):
    async def bad_post(url, **kw):
        return _JsonResp({"error": {"message": "terms"}}, status=400)

    async def bad_get(url, **kw):
        return _FakeResp(status=403, ctype="text/html", body=b"denied")

    monkeypatch.setattr(settings, "EXTRA_BRAIN_API_KEY", "gsk-test")
    monkeypatch.setattr(video._http, "post", bad_post)
    monkeypatch.setattr(video._http, "get", bad_get)
    assert run(video._narrate("a line to speak")) is None


def test_reel_with_voice_muxes_audio(rich_env, monkeypatch):
    captured = {}

    async def fake_post(url, **kw):
        if "chat/completions" in url:
            return _JsonResp({"choices": [{"message": {"content": '{"scenes": ["beach at dawn", "fishermen pulling nets", "boats in golden light"], "narration": "The Volta wakes before the city."}'}}]})
        # orpheus wav
        return _FakeResp(ctype="audio/wav", body=b"RIFF" + b"\x00" * 5000)

    monkeypatch.setattr(settings, "EXTRA_BRAIN_API_KEY", "gsk-test")
    monkeypatch.setattr(video._http, "post", fake_post)

    real_exec = asyncio.subprocess.create_subprocess_exec

    async def spy_exec(*cmd, **kw):
        captured["cmd"] = list(cmd)
        out = cmd[-1]
        with open(out, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42VOICED")
        return _FakeProc(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy_exec)
    stages: list[dict] = []
    url, _ = run(video.generate("volta fishermen at dawn", VideoOptions(duration=6),
                                on_progress=lambda d: stages.append(dict(d))))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", real_exec)
    assert "reel-" in url
    cmd = captured["cmd"]
    assert "[aout]" in cmd and "aac" in cmd  # narration actually muxed
    order = [s["stage"] for s in stages]
    assert order[0] == "storyboard" and "voice" in order and order[-1] == "compositing"


def test_reel_voice_all_fail_still_composes_silent(rich_env, monkeypatch):
    async def fake_post(url, **kw):
        if "chat/completions" in url:
            return _JsonResp({"choices": [{"message": {"content": '{"scenes": ["a", "b"], "narration": "speak me"}'}}]})
        return _JsonResp({"error": {}}, status=400)

    captured = {}

    async def spy_exec(*cmd, **kw):
        captured["cmd"] = list(cmd)
        with open(cmd[-1], "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42SILENT")
        return _FakeProc(0)

    monkeypatch.setattr(settings, "EXTRA_BRAIN_API_KEY", "gsk-test")
    monkeypatch.setattr(video._http, "post", fake_post)

    async def deny_get(url, **kw):
        return _FakeResp(status=403, ctype="text/html", body=b"no")

    # scenes must still fetch OK from the image provider
    async def scene_get(url, **kw):
        if "pollinations" in url:
            return _FakeResp()
        return _FakeResp(status=403, ctype="text/html", body=b"no")

    monkeypatch.setattr(video._http, "get", scene_get)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy_exec)
    stages: list[dict] = []
    url, _ = run(video.generate("quiet reel", VideoOptions(duration=6),
                                on_progress=lambda d: stages.append(dict(d))))
    assert "reel-" in url
    assert "[aout]" not in captured["cmd"]  # fail-open: no audio track
    voice_stage = [s for s in stages if s["stage"] == "voice"]
    assert voice_stage and voice_stage[-1]["done"] == 0


def test_reel_storyboard_off_keeps_deterministic(rich_env, monkeypatch):
    monkeypatch.setattr(settings, "REEL_STORYBOARD", False)
    called = {"n": 0}

    async def no_post(url, **kw):
        called["n"] += 1
        return _JsonResp({})

    monkeypatch.setattr(video._http, "post", no_post)
    monkeypatch.setattr(settings, "EXTRA_BRAIN_API_KEY", "gsk-test")
    url, _ = run(video.generate("deterministic beats reel", VideoOptions(duration=6)))
    assert "reel-" in url and called["n"] == 0  # never called the brain
