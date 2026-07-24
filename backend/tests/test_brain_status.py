"""Brain routing status helpers: text, image and video operational summaries."""

from app.config import settings
from app.services import brain_status as bs


def test_text_brain_status_surfaces_primary_and_fast(monkeypatch):
    monkeypatch.setattr(settings, "XAI_API_KEY", "xk")
    monkeypatch.setattr(settings, "ARENA_AI_API_KEY", "")
    monkeypatch.setattr(settings, "ARENA_AI_MODEL", "")
    monkeypatch.setattr(settings, "LLM_FALLBACK_PROVIDER", "")
    monkeypatch.setattr(settings, "FREETHEAI_API_KEY", "")
    monkeypatch.setattr(settings, "FREETHEAI_MODEL", "")
    monkeypatch.setattr(settings, "EXTRA_BRAIN_API_KEY", "")
    monkeypatch.setattr(settings, "EXTRA_BRAIN_MODEL", "")
    s = bs.text_brain_status()
    assert s["primary"]["provider"] == "xai"
    assert s["primary"]["model"] == settings.MODEL_CHAT
    assert s["fast"]["model"] == settings.MODEL_FAST
    assert s["ready"] is True


def test_image_brain_status_reports_pollinations_mode(monkeypatch):
    monkeypatch.setattr(settings, "IMAGE_FALLBACK_PROVIDER", "pollinations")
    monkeypatch.setattr(settings, "XAI_API_KEY", "")
    s = bs.image_brain_status()
    assert s["mode"] == "pollinations"
    assert s["pollinations"]["enabled"] is True
    assert s["ready"] is True


def test_video_brain_status_reports_chain_and_reasons(monkeypatch):
    monkeypatch.setattr(settings, "VIDEO_PROVIDER", "pollinations,reel,xai")
    monkeypatch.setattr(settings, "POLLINATIONS_API_KEY", "")
    monkeypatch.setattr(settings, "REEL_ENABLED", True)
    monkeypatch.setattr(settings, "XAI_API_KEY", "")
    monkeypatch.setattr(bs, "_ffmpeg_exe", lambda: "/usr/bin/ffmpeg")
    s = bs.video_brain_status()
    assert s["chain"] == ["pollinations", "reel", "xai"]
    by = {p["provider"]: p for p in s["providers"]}
    assert by["pollinations"]["ready"] is False
    assert by["reel"]["ready"] is True
    assert by["xai"]["ready"] is False
    assert s["ready"] is True
