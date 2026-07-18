"""🎨 Design Studio unit tests — presets, prompt compiler, provider gating,
ffmpeg argv builders, data-uri fetch, and the generate pipeline (mocked)."""

import base64

import pytest

from app.api.routes.media import SERVED_NAME_RE
from app.services import designer as dzn
from app.services import soundtrack


# ------------------------------------------------------------------ presets
def test_kind_presets_have_print_tier_bigger_than_web():
    assert set(dzn.KIND_PRESETS) == {"flyer", "logo", "banner"}
    for k, p in dzn.KIND_PRESETS.items():
        assert p.print_w > p.web_w and p.print_h > p.web_h, k
        # aspect consistency between web and print tiers (≤1% drift)
        assert abs(p.print_w / p.print_h - p.web_w / p.web_h) < 0.01, k
        assert p.gpt_image_size == f"{p.web_w}x{p.web_h}"


def test_style_and_palette_tables_non_empty():
    assert len(dzn.STYLE_PRESETS) >= 5 and "minimal" in dzn.STYLE_PRESETS
    assert "auto" in dzn.PALETTES and len(dzn.PALETTES) >= 5


# ------------------------------------------------------------ prompt compile
def test_compile_prompt_weaves_kind_style_palette_and_brief():
    p = dzn.compile_design_prompt("Launch party Friday 8pm", "flyer", "neon", "sunset")
    assert "flyer" in p.lower()
    assert dzn.STYLE_PRESETS["neon"] in p
    assert dzn.PALETTES["sunset"] in p
    assert "Launch party Friday 8pm" in p
    assert "watermark" in p.lower()


def test_compile_prompt_transparent_and_auto_palette():
    p = dzn.compile_design_prompt("Acme coffee cup mark", "logo", "minimal", "auto", transparent=True)
    assert "transparent background" in p
    for word in dzn.PALETTES.values():
        if word:
            assert word not in p  # auto palette injects no palette clause


def test_compile_prompt_unknown_kind_falls_back():
    p = dzn.compile_design_prompt("x", "poster", "nope", "nope")
    assert "flyer" in p.lower()


# ----------------------------------------------------------- provider gating
def test_native_opts_only_for_gpt_image_family():
    assert dzn.supports_native_image_opts("gpt-image-1")
    assert not dzn.supports_native_image_opts("grok-2-image-1212")
    assert dzn.provider_image_kwargs("grok-2-image-1212", "flyer", False) == {}


def test_native_kwargs_size_quality_and_transparent():
    kw = dzn.provider_image_kwargs("gpt-image-1", "logo", transparent=True)
    assert kw == {"size": "1024x1024", "quality": "high", "background": "transparent"}
    kw2 = dzn.provider_image_kwargs("gpt-image-1", "banner", transparent=False)
    assert kw2["size"] == "1536x1024" and "background" not in kw2


# --------------------------------------------------------------- argv builds
def test_normalize_cmd_cover_crop(monkeypatch):
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = dzn.build_normalize_cmd("in.png", "out.png", 1024, 1536)
    assert cmd[:3] == ["/bin/ffmpeg", "-y", "-i"]
    vf = cmd[cmd.index("-vf") + 1]
    assert "force_original_aspect_ratio=increase" in vf and "crop=1024:1536" in vf
    assert cmd[-1] == "out.png"


def test_upscale_cmd_300dpi_lanczos(monkeypatch):
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = dzn.build_upscale_cmd("in.png", "out.png", 2480, 3508)
    assert "scale=2480:3508:flags=lanczos" in cmd[cmd.index("-vf") + 1]
    i = cmd.index("-dpi")
    assert cmd[i + 1] == "300"


# ------------------------------------------------------------------- fetch
def test_fetch_image_bytes_decodes_data_uri():
    raw = b"\x89PNG\r\n\x1a\n" + b"x" * 600
    uri = "data:image/png;base64," + base64.b64encode(raw).decode()
    import asyncio

    assert asyncio.run(dzn._fetch_image_bytes(uri)) == raw


# ---------------------------------------------------------------- pipeline
def _fake_png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


def test_generate_design_no_ffmpeg_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(dzn.settings, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: None)

    async def fake_brief(idea, kind, style, palette):
        return f"AD: {idea}"

    async def fake_image(prompt, **kw):
        assert kw == {}  # default model is grok-2-image-1212 → no native opts
        return "data:image/png;base64," + base64.b64encode(_fake_png()).decode()

    monkeypatch.setattr(dzn, "enhance_brief", fake_brief)
    monkeypatch.setattr(dzn.llm, "generate_image", fake_image)

    import asyncio

    out = asyncio.run(dzn.generate_design("Coffee shop launch", "flyer", "bold", "gold"))
    assert out["brief"] == "AD: Coffee shop launch"
    assert (tmp_path / out["file"]).exists() and (tmp_path / out["print_file"]).exists()
    assert out["note"] and "ffmpeg" in out["note"]
    # raw staging file must be cleaned up
    assert not list(tmp_path.glob("*_raw.png"))


def test_generate_design_transparent_retry_without_native_bg(monkeypatch, tmp_path):
    monkeypatch.setattr(dzn.settings, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: None)
    monkeypatch.setattr(dzn.settings, "MODEL_IMAGE", "gpt-image-1")
    monkeypatch.setattr(dzn, "enhance_brief", lambda i, k, s, p: i)  # sync? no — always async in prod
    calls = []

    async def fake_image(prompt, **kw):
        calls.append(dict(kw))
        if kw.get("background") == "transparent":
            return None  # provider rejected transparent
        return "data:image/png;base64," + base64.b64encode(_fake_png()).decode()

    async def fake_brief(idea, kind, style, palette):
        return idea

    monkeypatch.setattr(dzn, "enhance_brief", fake_brief)
    monkeypatch.setattr(dzn.llm, "generate_image", fake_image)

    import asyncio

    out = asyncio.run(dzn.generate_design("Acme mark", "logo", "minimal", "auto", transparent=True, enhance=True))
    assert calls[0].get("background") == "transparent"
    assert "background" not in calls[1]
    assert out["native"] is True


def test_generate_design_rejects_unknown_kind():
    import asyncio

    with pytest.raises(dzn.DesignError):
        asyncio.run(dzn.generate_design("x", "postcard"))


# ------------------------------------------------------------- janitor guard
def test_design_filenames_are_not_publicly_served_or_swept():
    """Design files must neither be served by the public /media/files route
    nor swept by the 24h video janitor — they persist until owner deletes."""
    web = "a" * 32 + "_d.png"
    pr = "a" * 32 + "_dp.png"
    for name in (web, pr):
        assert not SERVED_NAME_RE.match(name), name
        assert not soundtrack.MEDIA_NAME_RE.match(name), name
        assert not soundtrack.MEDIA_POSTER_RE.match(name), name
